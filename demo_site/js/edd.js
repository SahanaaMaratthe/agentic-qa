/* KVTU practice portal: Electronic Document Delivery & Tracking System (eDDTS).
   FR-EDD-01..08, BR-EDD-01..04, eDDTS state machine. */
"use strict";

const DOCS = { PDC: "Provisional Degree Certificate", CMC: "Consolidated Marks Card", TRANSCRIPT: "Transcript", MIGRATION: "Migration Certificate" };
const NEEDS_CLEARED = ["PDC", "TRANSCRIPT"];                       // BR-EDD-01
const DELIVERY = { SELF: "Self-Pickup", SPEED: "Speed Post (India)", COURIER: "International Courier" };
const MAX_UPLOAD = 5 * 1024 * 1024;                                // FR-EDD-03: 5 MB
const EICAR = "EICAR-STANDARD-ANTIVIRUS-TEST-FILE";
const STATUS_LABEL = {
  DRAFT: "Draft", PAYMENT_PENDING: "Payment pending", UNDER_VERIFICATION: "Under verification", QUERY_RAISED: "Query raised",
  APPROVED_FOR_SIGNING: "Approved for signing", "SIGNED_&_PUBLISHED": "Signed & published", DISPATCHED: "Dispatched",
  REJECTED: "Rejected", REFUNDED: "Refunded",
};

function docName(k) { return t(DOCS[k] || k); }
function statusBadge(s) {
  const cls = { DRAFT: "grey", PAYMENT_PENDING: "amber", QUERY_RAISED: "amber", REJECTED: "red", REFUNDED: "red", DISPATCHED: "green" }[s] || "blue";
  return badge(t(STATUS_LABEL[s] || s), cls);
}
function app(id) { return Store.get().apps.find(a => a.id === id); }
function setStatus(a, to, actor, remark) { audit("APP", a.id, actor, a.status, to, remark); a.status = to; a.updated = now().toISOString(); Store.save(); }

function deliveryFee(mode) {
  const d = Store.get().delivery;
  if (mode === "COURIER") return bug("B15") ? 2250 : d.COURIER;                 // B15: courier charged 2,250 not 2,500
  return d[mode] ?? 0;
}
function feeOf(a) {
  const fees = Store.get().fees;
  const items = a.items.reduce((s, i) => s + (fees[i.type] || 0) * i.qty, 0);
  const del = (a.deliveryCharged ?? deliveryFee(a.delivery)) * (bug("B16") ? Math.max(1, a.items.length) : 1);  // B16: per item
  return { items, delivery: del, total: items + del };
}

/* ---------------------------------------------------------------- new / edit draft */
route("#/apply", {
  auth: "student",
  render: () => {
    const s = me(), d = Store.get();
    let a = d.apps.find(x => x.usn === s.usn && x.status === "DRAFT");
    if (!a) {
      a = { id: `APP-${now().getFullYear()}-${rand(6)}`, usn: s.usn, status: "DRAFT", items: [], delivery: "SELF",
            deliveryCharged: 0, address: "", country: "India", files: [], resubmits: 0, created: now().toISOString(),
            manualQueue: !!(s.legacy && !bug("B10")) };                                     // B10: legacy not flagged
      d.apps.push(a); Store.save(); audit("APP", a.id, s.usn, "-", "DRAFT", "Draft created");
    }
    setTimeout(() => go(`#/app/${a.id}`), 0);
    return `<p>${t("Opening your draft ...")}</p>`;
  },
});

route("#/app/:id", {
  auth: "student",
  render: ({ id }) => {
    const a = app(id), s = me();
    if (!a || a.usn !== s.usn) return `<section class="card"><h1>${t("Application not found")}</h1></section>`;
    const head = `<section class="card"><div class="row-head"><h1>${t("Application")} ${esc(a.id)}</h1>${statusBadge(a.status)}</div>
      ${a.manualQueue ? `<p class="note">${t("Your USN is from a batch before 2005. Your records will be verified manually by the Exam Section, which can take longer.")}</p>` : ""}
      ${timeline(a)}</section>`;
    if (a.status === "DRAFT") return head + draftForm(a);
    let body = summaryCard(a);
    if (a.status === "PAYMENT_PENDING") body += payCard(a);
    if (a.status === "QUERY_RAISED") body += queryCard(a);
    if (a.status === "UNDER_VERIFICATION" && bug("B22")) {                          // B22: refund after verification started
      body += `<section class="card"><h2>${t("Cancel and refund")}</h2><p class="muted">${t("Changed your mind? Request a refund of your fee.")}</p>
               <button id="refund" class="btn danger">${t("Request refund")}</button></section>`;
    }
    if (["SIGNED_&_PUBLISHED", "DISPATCHED"].includes(a.status)) body += certCard(a);
    if (a.paymentId) body += `<section class="card"><a class="btn" href="#/receipt/${esc(a.id)}">${t("View e-Receipt")}</a></section>`;
    return head + body;
  },
  after: ({ id }) => {
    const a = app(id); if (!a) return;
    if (a.status === "DRAFT") return draftAfter(a);
    if (a.status === "PAYMENT_PENDING") on("waive", "click", () => applyWaiver(a));
    if (a.status === "QUERY_RAISED") queryAfter(a);
    on("refund", "click", () => {
      const p = Store.get().payments.find(x => x.id === a.paymentId);
      Store.get().refunds.push({ appId: a.id, paymentId: a.paymentId, amount: p ? p.amount : 0, reason: "Student request",
                                 due: now().toISOString(), status: "Refunded" });
      setStatus(a, "REFUNDED", me().usn, "Refund requested by student");
      notify("SMS", me().mobile, `KVTU: Refund for ${a.id} processed.`);
      flash("ok", t("Refund processed.")); render();
    });
  },
});

function timeline(a) {
  const log = Store.get().audit.filter(x => x.entity === "APP" && x.id === a.id);
  const when = to => (log.find(x => x.to === to) || {}).ts;
  let steps = [["Submitted", when("PAYMENT_PENDING")], ["Paid", when("UNDER_VERIFICATION")],
               ["Verified", when("APPROVED_FOR_SIGNING")], ["Signed", when("SIGNED_&_PUBLISHED")], ["Dispatched", when("DISPATCHED")]];
  if (bug("B35")) steps = steps.filter(s => s[0] !== "Verified");                       // B35: "Verified" milestone missing
  return `<ol class="timeline">${steps.map(([l, ts]) => `<li class="${ts ? "done" : ""}"><b>${t(l)}</b><span>${ts ? fmt(ts) : "—"}</span></li>`).join("")}</ol>`;
}

function itemsTable(a, editable) {
  const fees = Store.get().fees;
  if (!a.items.length) return `<p class="muted">${t("No documents added yet.")}</p>`;
  return `<table class="grid" id="cart"><thead><tr><th>${t("Document")}</th><th>${t("Copies")}</th><th>${t("Fee per copy")}</th><th>${t("Amount")}</th>${editable ? "<th></th>" : ""}</tr></thead><tbody>
    ${a.items.map((i, n) => `<tr data-row="${n}"><td>${docName(i.type)}</td><td>${i.qty}</td><td>${inr(fees[i.type])}</td><td>${inr(fees[i.type] * i.qty)}</td>
      ${editable ? `<td><button class="link danger" data-remove="${n}" aria-label="${t("Remove")} ${docName(i.type)}">${t("Remove")}</button></td>` : ""}</tr>`).join("")}
  </tbody></table>`;
}

function feeBox(a) {
  const f = feeOf(a);
  return `<div class="fee" id="feebox" aria-live="polite">
    <div><span>${t("Documents")}</span><b>${inr(f.items)}</b></div>
    <div><span>${t("Delivery")} (${t(DELIVERY[a.delivery])})</span><b>${inr(f.delivery)}</b></div>
    <div class="total"><span>${t("Total fee")}</span><b id="total">${inr(f.total)}</b></div></div>`;
}

function draftForm(a) {
  const files = a.files.map(f => fileChip(f)).join("") || `<p class="muted">${t("No files uploaded yet.")}</p>`;
  return `
  <section class="card">
    <h2>1. ${t("Choose documents")}</h2>
    <form id="f-add" class="inline">
      ${field("doctype", "Document", `<select id="doctype">${Object.keys(DOCS).map(k => `<option value="${k}">${docName(k)}</option>`).join("")}</select>`)}
      ${field("qty", "Copies", `<input id="qty" type="number" min="1" max="10" value="1">`, t("1 to 10 copies"))}
      <button class="btn" type="submit">${t("Add to request")}</button>
    </form>
    ${itemsTable(a, true)}
  </section>
  <section class="card">
    <h2>2. ${t("Delivery")}</h2>
    <fieldset class="radios"><legend class="sr-only">${t("Delivery mode")}</legend>
      ${Object.entries(DELIVERY).map(([k, l]) => `<label><input type="radio" name="delivery" value="${k}" ${a.delivery === k ? "checked" : ""}> ${t(l)}
        <span class="muted">(${inr(deliveryFee(k))})</span></label>`).join("")}
    </fieldset>
    <div id="addr-box" class="${a.delivery === "SELF" ? "hidden" : ""}">
      ${field("address", "Delivery address", `<textarea id="address" rows="3">${esc(a.address)}</textarea>`)}
      <div id="country-box" class="${a.delivery === "COURIER" ? "" : "hidden"}">
        ${field("country", "Country", `<select id="country">${["India", "United States", "United Kingdom", "Germany", "Australia", "Canada", "UAE"].map(c =>
          `<option ${a.country === c ? "selected" : ""}>${c}</option>`).join("")}</select>`)}</div>
    </div>
  </section>
  <section class="card">
    <h2>3. ${t("Upload documents")}</h2>
    <p class="muted">${t("Government ID (Aadhaar or Passport) and your semester grade cards are required. PDF, JPG or PNG, up to 5 MB each.")}</p>
    <div class="uploads">
      ${field("f-id", "Government ID (Aadhaar / Passport)", `<input id="f-id" type="file" accept=".pdf,.jpg,.jpeg,.png">`)}
      ${field("f-grade", "Semester grade cards", `<input id="f-grade" type="file" accept=".pdf,.jpg,.jpeg,.png" multiple>`)}
    </div>
    <div id="upload-msg" role="status"></div>
    <div class="chips" id="files">${files}</div>
  </section>
  <section class="card">
    <h2>4. ${t("Fee")}</h2>
    ${feeBox(a)}
    <button id="to-pay" class="btn primary">${t("Proceed to Pay")}</button>
  </section>`;
}

function fileChip(f, removable = true) {
  const thumb = f.thumb ? `<img src="${f.thumb}" alt="${t("Preview of")} ${esc(f.name)}">` : `<div class="pdf-thumb" aria-hidden="true">PDF</div>`;
  return `<div class="chip">${thumb}<div><b>${esc(f.name)}</b><span>${t(f.slot === "ID" ? "Government ID" : "Grade card")} · ${(f.size / 1024 / 1024).toFixed(2)} MB</span></div></div>`;
}

function draftAfter(a) {
  on("f-add", "submit", e => {
    e.preventDefault();
    const s = me(), type = $("doctype").value, qty = Number($("qty").value);
    if (!Number.isInteger(qty) || (!bug("B07") && qty < 1) || (!bug("B06") && qty > 10)) {     // B06: >10, B07: 0 copies
      flash("error", t("Copies must be a whole number from 1 to 10.")); return render();
    }
    const blocked = bug("B09") ? ["TRANSCRIPT"] : NEEDS_CLEARED;                               // B09: PDC not checked
    if (blocked.includes(type) && !s.cleared) {
      flash("error", t("You are not yet eligible for this document: University records show exams still to be cleared.")); return render();
    }
    const ex = a.items.find(i => i.type === type);
    if (ex) {
      if (!bug("B06") && ex.qty + qty > 10) { flash("error", t("Copies must be a whole number from 1 to 10.")); return render(); }
      ex.qty += qty;
    } else a.items.push({ type, qty });
    Store.save(); render();
  });
  const bindRemove = () => document.querySelectorAll("[data-remove]").forEach(b => b.addEventListener("click", () => {
    a.items.splice(Number(b.dataset.remove), 1); Store.save();
    if (bug("B08")) {                                                                            // B08: cart updates, total does not
      const tbl = $("cart"); if (tbl) tbl.outerHTML = itemsTable(a, true); else render();
      bindRemove(); return;
    }
    render();
  }));
  bindRemove();
  document.querySelectorAll("input[name=delivery]").forEach(r => r.addEventListener("change", () => {
    const prev = a.deliveryCharged ?? 0;
    a.delivery = r.value;
    const fee = deliveryFee(r.value);
    a.deliveryCharged = bug("B17") ? Math.max(prev, fee) : fee;                                   // B17: fee never goes down
    Store.save();
    $("addr-box").classList.toggle("hidden", a.delivery === "SELF");
    $("country-box").classList.toggle("hidden", a.delivery !== "COURIER");
    $("feebox").outerHTML = feeBox(a);
  }));
  on("address", "input", () => { a.address = $("address").value; Store.save(); });
  on("country", "change", () => { a.country = $("country").value; Store.save(); $("feebox").outerHTML = feeBox(a); });
  on("f-id", "change", e => handleFiles(a, e.target.files, "ID"));
  on("f-grade", "change", e => handleFiles(a, e.target.files, "GRADE"));
  on("to-pay", "click", () => {
    const problems = [];
    if (!a.items.length) problems.push(t("Add at least one document."));
    if (!a.files.some(f => f.slot === "ID")) problems.push(t("Upload your Government ID."));
    if (!bug("B14") && !a.files.some(f => f.slot === "GRADE")) problems.push(t("Upload your semester grade cards."));   // B14
    if (a.delivery !== "SELF" && a.address.trim().length < 10) problems.push(t("Enter a complete delivery address."));
    if (problems.length) { flash("error", problems.join("<br>")); return render(); }
    a.lockedFee = feeOf(a).total;                                                                 // BR-EDD-03: locked at checkout
    setStatus(a, "PAYMENT_PENDING", me().usn, "Proceed to Pay");
    go(`#/app/${a.id}`);
  });
}

/* FR-EDD-03: type by content (magic bytes), size, virus scan, thumbnail */
async function handleFiles(a, list, slot) {
  const msgs = [];
  for (const file of Array.from(list)) {
    const ext = (file.name.split(".").pop() || "").toLowerCase();
    if (!["pdf", "jpg", "jpeg", "png"].includes(ext)) { msgs.push(`${esc(file.name)}: ${t("only PDF, JPG or PNG files are accepted.")}`); continue; }
    const limit = bug("B11") ? MAX_UPLOAD + 512 * 1024 : MAX_UPLOAD;                               // B11: 5.5 MB accepted
    if (file.size > limit) { msgs.push(`${esc(file.name)}: ${t("file is larger than 5 MB.")}`); continue; }
    const head = new Uint8Array(await file.slice(0, 8).arrayBuffer());
    const kind = head[0] === 0x25 && head[1] === 0x50 && head[2] === 0x44 && head[3] === 0x46 ? "pdf"
               : head[0] === 0x89 && head[1] === 0x50 && head[2] === 0x4E && head[3] === 0x47 ? "png"
               : head[0] === 0xFF && head[1] === 0xD8 && head[2] === 0xFF ? "jpg" : null;
    const claimed = ext === "jpeg" ? "jpg" : ext;
    if (!bug("B12") && kind !== claimed) { msgs.push(`${esc(file.name)}: ${t("the file is corrupt or is not really a")} ${ext.toUpperCase()}.`); continue; }  // B12
    const scan = !(bug("B13") && claimed !== "pdf");                                              // B13: images not scanned
    if (scan) {
      const text = await file.slice(0, Math.min(file.size, 2 * 1024 * 1024)).text();
      if (text.includes(EICAR)) { msgs.push(`${esc(file.name)}: ${t("virus detected. The file was rejected.")}`); continue; }
    }
    let thumb = null;
    if (claimed !== "pdf" && kind) thumb = await makeThumb(file);
    a.files.push({ name: file.name, size: file.size, kind: claimed, slot, thumb, at: now().toISOString() });
    msgs.push(`${esc(file.name)}: ${t("uploaded and scanned clean.")}`);
  }
  Store.save();
  flash(msgs.some(m => !m.includes(t("uploaded and scanned clean."))) ? "error" : "ok", msgs.join("<br>"));
  render();
}
function makeThumb(file) {
  return new Promise(res => {
    const img = new Image(), url = URL.createObjectURL(file);
    img.onload = () => { const c = document.createElement("canvas"), r = 96 / Math.max(img.width, img.height);
      c.width = img.width * r; c.height = img.height * r; c.getContext("2d").drawImage(img, 0, 0, c.width, c.height);
      URL.revokeObjectURL(url); res(c.toDataURL("image/jpeg", 0.6)); };
    img.onerror = () => res(null); img.src = url;
  });
}

function summaryCard(a) {
  return `<section class="card"><h2>${t("Request summary")}</h2>${itemsTable(a, false)}
    <p>${t("Delivery")}: <b>${t(DELIVERY[a.delivery])}</b>${a.delivery !== "SELF" ? ` · ${esc(a.address)}${a.delivery === "COURIER" ? ", " + esc(a.country) : ""}` : ""}</p>
    <p>${t("Total fee")}: <b>${inr(payAmount(a))}</b></p>
    <div class="chips">${a.files.map(f => fileChip(f)).join("")}</div>
    ${a.queryRemark ? `<p class="note"><b>${t("Query from Exam Section")}:</b> ${esc(a.queryRemark)}</p>` : ""}</section>`;
}

/* ---------------------------------------------------------------- payment: FR-EDD-05 */
function payAmount(a) { return bug("B18") ? feeOf(a).total : (a.lockedFee ?? feeOf(a).total); }   // B18: fee not locked

function payCard(a) {
  return `<section class="card"><h2>${t("Pay fee")}</h2>
    <p>${t("Amount to pay")}: <b class="big">${inr(payAmount(a))}</b></p>
    <a class="btn primary" href="#/gateway/${esc(a.id)}">${t("Pay now")}</a>
    <details class="waiver"><summary>${t("I have a fee waiver code from the Registrar (Evaluation)")}</summary>
      ${field("wcode", "Waiver code", `<input id="wcode" autocomplete="off">`)}<button id="waive" class="btn">${t("Apply waiver")}</button></details>
  </section>`;
}

function applyWaiver(a) {
  const d = Store.get(), code = val("wcode").toUpperCase();
  const w = d.waivers.find(x => x.code === code && (bug("B19") || (x.appId === a.id && !x.used)));     // B19: any code, reusable
  if (!w) { flash("error", t("This waiver code is not valid for this application.")); return render(); }
  w.used = true;
  const pid = newPaymentId();
  d.payments.push({ id: pid, appId: a.id, gatewayRef: "WAIVER-" + code, mode: "WAIVER", amount: 0, status: "SUCCESS", settledAt: now().toISOString() });
  a.paymentId = pid; a.paidAmount = 0;
  setStatus(a, "UNDER_VERIFICATION", me().usn, `Fee waived with code ${code}`);
  notify("SMS", me().mobile, `KVTU: Fee for ${a.id} waived. Your application is under verification.`);
  flash("ok", t("Fee waived. Your application is now under verification.")); render();
}

function newPaymentId() { const n = Store.nextSeq("pay"); return `PAY${now().toISOString().slice(0, 10).replace(/-/g, "")}${String(n).padStart(6, "0")}`; }

route("#/gateway/:id", {
  auth: "student",
  render: ({ id }) => {
    const a = app(id);
    if (!a || a.status !== "PAYMENT_PENDING") return `<section class="card"><h1>${t("Nothing to pay")}</h1><a href="#/student">${t("Dashboard")}</a></section>`;
    return `<section class="card narrow gateway">
      <div class="gw-head">SBI ePay · ${t("practice gateway")}</div>
      <p>${t("Merchant")}: KVTU eDDTS · ${t("Reference")}: ${esc(a.id)}</p>
      <p class="big">${inr(payAmount(a))}</p>
      <fieldset class="radios"><legend>${t("Payment method")}</legend>
        ${["UPI", "Card", "NetBanking"].map((m, i) => `<label><input type="radio" name="pm" value="${m}" ${i === 0 ? "checked" : ""}> ${t(m)}</label>`).join("")}</fieldset>
      ${field("outcome", "Bank response (practice)", `<select id="outcome"><option value="SUCCESS">${t("Success")}</option><option value="FAILED">${t("Failure (declined by bank)")}</option><option value="DUPLICATE">${t("Success, but the bank debited twice")}</option></select>`)}
      <button id="paybtn" class="btn primary">${t("Pay")} ${inr(payAmount(a))}</button>
    </section>`;
  },
  after: ({ id }) => {
    let busy = false;
    on("paybtn", "click", () => {
      const a = app(id);
      if (!bug("B25")) { if (busy || a.status !== "PAYMENT_PENDING") return; busy = true; $("paybtn").disabled = true; }   // B25: double click = 2 payments
      const mode = document.querySelector("input[name=pm]:checked").value, outcome = $("outcome").value;
      const pid = newPaymentId(), amount = payAmount(a);
      const status = outcome === "FAILED" ? "FAILED" : "SUCCESS";
      Store.get().payments.push({ id: pid, appId: a.id, gatewayRef: "SBI" + rand(10, "0123456789"), mode, amount, status,
                                  settledAt: status === "SUCCESS" ? now().toISOString() : null });
      Store.save();
      if (outcome === "DUPLICATE") {
        const dup = newPaymentId();
        Store.get().payments.push({ id: dup, appId: a.id, gatewayRef: "SBI" + rand(10, "0123456789"), mode, amount, status: "SUCCESS", duplicate: true, settledAt: now().toISOString() });
        const days = bug("B23") ? 7 : 5;                                                                     // B23: T+7 not T+5
        Store.get().refunds.push({ appId: a.id, paymentId: dup, amount, reason: "Duplicate gateway debit (auto-refund)",
                                   due: addCalendarDays(now(), days).toISOString(), status: "Scheduled" });
        Store.save();
      }
      const payload = `${a.id}|${amount}|${status}|${pid}`;
      setTimeout(() => { webhook(payload, hmac(payload)); go(`#/app/${a.id}`); }, 600);                         // async server-to-server callback
    });
  },
});

/* gateway -> portal callback (HMAC-verified): PAYMENT_PENDING -> UNDER_VERIFICATION */
function webhook(payload, signature) {
  const [appId, amount, status, pid] = payload.split("|");
  const a = app(appId);
  if (!a) return "unknown application";
  if (!bug("B21") && signature !== hmac(payload)) {                                                       // B21: signature not checked
    audit("APP", a.id, "payment-gateway", a.status, a.status, "Webhook rejected: invalid signature");
    return "rejected";
  }
  if (!bug("B21") && Number(amount) !== payAmount(a)) { audit("APP", a.id, "payment-gateway", a.status, a.status, "Webhook rejected: amount mismatch"); return "rejected"; }
  if (a.status !== "PAYMENT_PENDING") return "ignored";
  if (status !== "SUCCESS" && !bug("B20")) {                                                              // B20: failure treated as paid
    notify("SMS", student(a.usn).mobile, `KVTU: Payment for ${a.id} failed. No money was taken. Please try again.`);
    audit("APP", a.id, "payment-gateway", a.status, a.status, "Payment failed");
    return "failed";
  }
  a.paymentId = pid; a.paidAmount = Number(amount);
  setStatus(a, "UNDER_VERIFICATION", "payment-gateway", "Payment confirmed (webhook)");
  const s = student(a.usn);
  notify("SMS", s.mobile, `KVTU: Payment of ${inr(amount)} received for ${a.id}. e-Receipt sent to your e-mail.`);
  notify("Email", s.email, `Payment received for application ${a.id}. Amount ${inr(amount)}. Your e-Receipt is attached (practice).`);
  return "ok";
}

route("#/receipt/:id", {
  auth: "student",
  render: ({ id }) => {
    const a = app(id), p = a && Store.get().payments.find(x => x.id === a.paymentId), s = me();
    if (!p) return `<section class="card"><h1>${t("No receipt")}</h1></section>`;
    return `<section class="card receipt" id="receipt">
      <h1>${t("e-Receipt")}</h1>
      <table class="kv"><tr><th>${t("Receipt / payment ID")}</th><td>${esc(p.id)}</td></tr>
        <tr><th>${t("Application ID")}</th><td>${esc(a.id)}</td></tr>
        <tr><th>${t("Name")}</th><td>${esc(s.name)} (${esc(s.usn)})</td></tr>
        <tr><th>${t("Amount paid")}</th><td>${inr(p.amount)}</td></tr>
        <tr><th>${t("Payment method")}</th><td>${esc(bug("B24") && p.mode !== "WAIVER" ? "UPI" : p.mode)}</td></tr>    <!-- B24 -->
        <tr><th>${t("Bank reference")}</th><td>${esc(p.gatewayRef)}</td></tr>
        <tr><th>${t("Date")}</th><td>${fmt(p.settledAt)}</td></tr></table>
      ${itemsTable(a, false)}
      <button class="btn no-print" onclick="window.print()">${t("Download / print as PDF")}</button>
    </section>`;
  },
});

/* ---------------------------------------------------------------- query & re-upload */
function queryCard(a) {
  const left = 2 - a.resubmits;
  const blocked = !bug("B27") && left <= 0;                                                                   // B27: unlimited
  return `<section class="card"><h2>${t("Respond to the query")}</h2>
    ${blocked ? `<p class="note">${t("You have used both re-submissions. Please contact the Exam Section.")}</p>`
      : `<p class="muted">${t("Upload the corrected document(s). Re-submissions left")}: <b>${Math.max(left, 0)}</b></p>
         ${field("f-fix", "Corrected file(s)", `<input id="f-fix" type="file" accept=".pdf,.jpg,.jpeg,.png" multiple>`)}
         <button id="resubmit" class="btn primary">${t("Re-submit for verification")}</button>`}
  </section>`;
}
function queryAfter(a) {
  on("f-fix", "change", e => handleFiles(a, e.target.files, "GRADE"));
  on("resubmit", "click", () => {
    a.resubmits++; a.queryRemark = "";
    setStatus(a, "UNDER_VERIFICATION", me().usn, `Re-submitted (${a.resubmits})`);
    notify("Email", "exam.section@kvtu.example", `Application ${a.id} re-submitted by ${a.usn}.`);
    flash("ok", t("Re-submitted. The Exam Section has been alerted.")); render();
  });
}

/* ---------------------------------------------------------------- certificate & QR */
function certCard(a) {
  const link = `#/verify?h=${a.qrHash}`;
  return `<section class="card"><h2>${t("Digital certificate")}</h2>
    <div class="cert">${qrSvg(a.qrHash)}<div><p>${t("Signed by the Registrar (Evaluation) and pushed to NAD / DigiLocker.")}</p>
      <p class="mono small">SHA-256: ${esc(a.qrHash)}</p><a href="${link}">${t("Open public verification page")}</a>
      <p class="muted small">${t("Practice QR: not scannable; use the link.")}</p></div></div></section>`;
}
function qrSvg(h) {
  let cells = "";
  for (let i = 0; i < 21 * 21; i++) { const bit = parseInt(h[i % 64], 16) >> (i % 4) & 1; if (bit) cells += `<rect x="${i % 21}" y="${Math.floor(i / 21)}" width="1" height="1"/>`; }
  return `<svg class="qr" viewBox="0 0 21 21" role="img" aria-label="${t("QR code")}">${cells}</svg>`;
}

/* ---------------------------------------------------------------- public tracking: FR-EDD-08 */
route("#/track", {
  render: p => `
  <section class="card narrow"><h1>${t("Track application")}</h1>
    <p class="muted">${t("No login needed. Enter your Application ID and USN.")}</p>
    <form id="f-track">${field("tapp", "Application ID", `<input id="tapp" value="${esc(p.app || "")}">`)}
      ${field("tusn", "University Seat Number (USN)", `<input id="tusn">`)}<button class="btn primary">${t("Track")}</button></form>
    <div id="track-out"></div></section>`,
  after: () => on("f-track", "submit", e => {
    e.preventDefault();
    const a = app(val("tapp").toUpperCase()), u = normUsn(val("tusn"));
    if (!a || (!bug("B34") && a.usn !== u)) {                                                               // B34: USN not checked
      $("track-out").innerHTML = `<p class="flash error">${t("No application matches this Application ID and USN.")}</p>`; return;
    }
    const d = Store.get().audit.filter(x => x.id === a.id && x.to === "DISPATCHED").pop();
    $("track-out").innerHTML = `<h2>${esc(a.id)} ${statusBadge(a.status)}</h2>${timeline(a)}
      ${a.awb ? `<p>${t("India Post tracking number")}: <b>${esc(a.awb)}</b> · <a href="https://www.indiapost.gov.in/" target="_blank" rel="noopener">${t("Track on India Post")}</a></p>` : ""}
      ${d ? `<p class="muted">${t("Dispatched on")} ${fmt(d.ts)}</p>` : ""}`;
  }),
});

/* ---------------------------------------------------------------- public verification: FR-EDD-07 */
route("#/verify", {
  render: p => `
  <section class="card narrow"><h1>${t("Verify a certificate")}</h1>
    <form id="f-ver">${field("hash", "Verification code (from the QR)", `<input id="hash" class="mono" value="${esc(p.h || "")}">`)}
      <button class="btn primary">${t("Verify")}</button></form><div id="ver-out"></div></section>`,
  after: p => {
    const run = () => {
      const h = val("hash").toLowerCase();
      const a = Store.get().apps.find(x => x.qrHash && (bug("B32") ? h.length >= 8 && x.qrHash.startsWith(h.slice(0, 8)) : x.qrHash === h));   // B32
      if (!a) { $("ver-out").innerHTML = `<p class="flash error">${t("NOT VERIFIED: no certificate matches this code.")}</p>`; return; }
      const s = student(a.usn), d = Store.get();
      $("ver-out").innerHTML = `<div class="flash ok"><b>${t("AUTHENTIC")}</b>: ${t("issued by Kaveri Valley Technological University")}</div>
        <table class="kv"><tr><th>${t("Name")}</th><td>${esc(s.name)}</td></tr><tr><th>${t("USN")}</th><td>${esc(s.usn)}</td></tr>
        <tr><th>${t("College")}</th><td>${esc(d.colleges[s.college])}</td></tr>
        <tr><th>${t("Documents")}</th><td>${a.items.map(i => docName(i.type)).join(", ")}</td></tr>
        <tr><th>${t("Signed on")}</th><td>${fmt(a.signedAt)}</td></tr>
        ${bug("B31") ? `<tr><th>${t("Date of birth")}</th><td>${esc(s.dob)}</td></tr><tr><th>${t("Mobile")}</th><td>${esc(s.mobile)}</td></tr>` : ""}</table>`;   // B31: PII shown
    };
    on("f-ver", "submit", e => { e.preventDefault(); run(); });
    if (p.h) run();
  },
});

/* ================================================================= STAFF: clerk (FR-EDD-06) */
route("#/staff/clerk", {
  auth: ["clerk"],
  render: () => {
    const list = Store.get().apps.filter(a => ["UNDER_VERIFICATION", "QUERY_RAISED"].includes(a.status));
    return `<section class="card"><h1>${t("Scrutiny workbench")}</h1>
      ${list.length ? `<table class="grid"><thead><tr><th>${t("Application ID")}</th><th>${t("USN")}</th><th>${t("Documents")}</th><th>${t("Status")}</th><th></th></tr></thead><tbody>
      ${list.map(a => `<tr><td>${esc(a.id)} ${a.manualQueue ? badge(t("Legacy: manual check"), "amber") : ""}</td><td>${esc(a.usn)}</td>
        <td>${a.items.map(i => `${docName(i.type)} × ${i.qty}`).join("<br>")}</td><td>${statusBadge(a.status)}</td>
        <td><a href="#/staff/clerk/${esc(a.id)}">${t("Review")}</a></td></tr>`).join("")}</tbody></table>`
      : `<p class="muted">${t("Nothing waiting for verification.")}</p>`}</section>`;
  },
});

route("#/staff/clerk/:id", {
  auth: ["clerk"],
  render: ({ id }) => {
    const a = app(id); if (!a) return `<section class="card"><h1>${t("Not found")}</h1></section>`;
    const s = student(a.usn), tr = Store.get().tr[a.usn] || {};
    return `<section class="card"><div class="row-head"><h1>${t("Review")} ${esc(a.id)}</h1>${statusBadge(a.status)}</div>
      <div class="split">
        <div><h2>${t("Uploaded by applicant")}</h2><p>${esc(s.name)} · ${esc(s.usn)}</p>${itemsTable(a, false)}
          <div class="chips">${a.files.map(f => fileChip(f)).join("")}</div>
          <p class="muted">${t("Re-submissions used")}: ${a.resubmits} / 2</p></div>
        <div><h2>${t("Tabulation Register")}</h2>
          <table class="kv"><tr><th>${t("Result")}</th><td>${esc(tr.result || "-")}</td></tr>
          <tr><th>SGPA</th><td>${(tr.sgpa || []).map((g, i) => `S${i + 1}: ${g || "—"}`).join(" · ") || "-"}</td></tr></table></div>
      </div>
      ${a.status === "UNDER_VERIFICATION" ? `
      ${field("remark", "Remark", `<textarea id="remark" rows="2"></textarea>`, t("Required for Query and Reject."))}
      <div class="actions"><button id="approve" class="btn primary">${t("Approve")}</button>
        <button id="query" class="btn">${t("Raise query")}</button><button id="reject" class="btn danger">${t("Reject")}</button></div>` : ""}
    </section>`;
  },
  after: ({ id }) => {
    const a = app(id), clerk = staffMe().user;
    on("approve", "click", () => {
      const s = student(a.usn);
      if (!bug("B28") && a.items.some(i => NEEDS_CLEARED.includes(i.type)) && !s.cleared) {            // B28: TR check skipped
        flash("error", t("Cannot approve: the Tabulation Register shows exams not yet cleared.")); return render();
      }
      setStatus(a, "APPROVED_FOR_SIGNING", clerk, val("remark") || "Verified against Tabulation Register");
      flash("ok", t("Approved for signing.")); go("#/staff/clerk");
    });
    on("query", "click", () => {
      const r = val("remark");
      if (!r && !bug("B26")) { flash("error", t("A remark explaining what is missing is required.")); return render(); }   // B26
      if (!bug("B27") && a.resubmits >= 2) { flash("error", t("Both re-submissions are used. Approve or reject the application.")); return render(); }
      a.queryRemark = r; setStatus(a, "QUERY_RAISED", clerk, r);
      const s = student(a.usn), msg = `KVTU: Query on ${a.id}: ${r || "(no details)"}. Re-upload at the portal.`;
      notify("SMS", s.mobile, msg);
      if (!bug("B29")) notify("Email", s.email, `${msg} Link: #/app/${a.id}`);                         // B29: no e-mail
      flash("ok", t("Query raised and the applicant notified.")); go("#/staff/clerk");
    });
    on("reject", "click", () => {
      const r = val("remark");
      if (!r) { flash("error", t("A remark explaining the rejection is required.")); return render(); }
      setStatus(a, "REJECTED", clerk, r);
      notify("SMS", student(a.usn).mobile, `KVTU: Application ${a.id} was rejected: ${r}`);
      go("#/staff/clerk");
    });
  },
});

/* ================================================================= STAFF: registrar (FR-EDD-07, BR-EDD-03 waivers) */
route("#/staff/registrar", {
  auth: ["registrar"],
  render: () => {
    const d = Store.get(), list = d.apps.filter(a => a.status === "APPROVED_FOR_SIGNING");
    const pending = d.apps.filter(a => a.status === "PAYMENT_PENDING");
    return `<section class="card"><h1>${t("Signing desk")}</h1>
      ${field("dsc", "Digital Signature Certificate (DSC)", `<select id="dsc">${d.dsc.map(c => `<option value="${c.id}">${esc(c.label)}</option>`).join("")}</select>`)}
      ${list.length ? `<table class="grid"><thead><tr><th>${t("Application ID")}</th><th>${t("USN")}</th><th>${t("Documents")}</th><th></th></tr></thead><tbody>
        ${list.map(a => `<tr><td>${esc(a.id)}</td><td>${esc(a.usn)}</td><td>${a.items.map(i => docName(i.type)).join(", ")}</td>
        <td><button class="btn primary" data-sign="${esc(a.id)}">${t("Sign & push to NAD")}</button></td></tr>`).join("")}</tbody></table>`
      : `<p class="muted">${t("Nothing waiting for signature.")}</p>`}</section>
      <section class="card"><h2>${t("Fee waiver authorisation")}</h2>
      ${pending.length ? `${field("wapp", "Application awaiting payment", `<select id="wapp">${pending.map(a => `<option>${esc(a.id)}</option>`).join("")}</select>`)}
        <button id="issue" class="btn">${t("Issue waiver code")}</button><div id="code-out"></div>`
      : `<p class="muted">${t("No applications awaiting payment.")}</p>`}</section>`;
  },
  after: () => {
    document.querySelectorAll("[data-sign]").forEach(b => b.addEventListener("click", () => {
      const a = app(b.dataset.sign), c = Store.get().dsc.find(x => x.id === $("dsc").value);
      const expired = new Date(c.validUntil + "T23:59:59") < now();
      if (c.cls !== 3 || (expired && !bug("B30"))) {                                                       // B30: expired DSC accepted
        flash("error", t("This certificate cannot be used: a valid Class-3 DSC is required.")); return render();
      }
      a.signedAt = now().toISOString();
      a.qrHash = sha256(`${a.id}|${a.usn}|${a.items.map(i => i.type + "x" + i.qty).join(",")}|${a.signedAt}`);
      setStatus(a, "SIGNED_&_PUBLISHED", staffMe().user, `Signed with ${c.id}; pushed to NAD`);
      notify("Email", student(a.usn).email, `Your certificate for ${a.id} is signed and available in DigiLocker/NAD. Verify: #/verify?h=${a.qrHash}`);
      flash("ok", t("Signed and pushed to NAD.")); render();
    }));
    on("issue", "click", () => {
      const code = "WVR-" + rand(6);
      Store.get().waivers.push({ code, appId: $("wapp").value, used: false, by: staffMe().user, at: now().toISOString() });
      Store.save(); audit("APP", $("wapp").value, staffMe().user, "PAYMENT_PENDING", "PAYMENT_PENDING", `Waiver code ${code} issued`);
      $("code-out").innerHTML = `<p class="flash ok">${t("Waiver code")}: <b class="mono">${code}</b> (${t("for")} ${esc($("wapp").value)})</p>`;
    });
  },
});

/* ================================================================= STAFF: dispatch */
route("#/staff/dispatch", {
  auth: ["dispatch"],
  render: () => {
    const list = Store.get().apps.filter(a => a.status === "SIGNED_&_PUBLISHED");
    return `<section class="card"><h1>${t("Dispatch desk")}</h1>
      ${list.length ? list.map(a => `<div class="dispatch-row"><div><b>${esc(a.id)}</b> · ${t(DELIVERY[a.delivery])}<br><span class="muted">${esc(a.address || t("Collect at counter"))}</span></div>
        ${a.delivery === "SELF" ? `<button class="btn" data-hand="${esc(a.id)}">${t("Mark handed over")}</button>`
          : `<input id="awb-${esc(a.id)}" placeholder="EE123456789IN" aria-label="${t("India Post tracking number for")} ${esc(a.id)}">
             <button class="btn primary" data-awb="${esc(a.id)}">${t("Save tracking & dispatch")}</button>`}</div>`).join("")
      : `<p class="muted">${t("Nothing to dispatch.")}</p>`}</section>`;
  },
  after: () => {
    const done = (a, awb) => {
      a.awb = awb || ""; setStatus(a, "DISPATCHED", staffMe().user, awb ? `India Post ${awb}` : "Handed over at counter");
      const s = student(a.usn);
      notify("SMS", s.mobile, `KVTU: ${a.id} dispatched.${awb ? " India Post tracking: " + awb : ""}`);
      notify("Email", s.email, `Your documents for ${a.id} have been dispatched.${awb ? " Tracking number " + awb : ""}`);
      flash("ok", t("Dispatched.")); render();
    };
    document.querySelectorAll("[data-hand]").forEach(b => b.addEventListener("click", () => done(app(b.dataset.hand), "")));
    document.querySelectorAll("[data-awb]").forEach(b => b.addEventListener("click", () => {
      const awb = val("awb-" + b.dataset.awb).toUpperCase();
      const ok = bug("B33") ? /^[A-Z]{2}\d{8,9}[A-Z]{2}$/.test(awb) : /^[A-Z]{2}\d{9}[A-Z]{2}$/.test(awb);      // B33: 12 chars accepted
      if (!ok) { flash("error", t("Enter a valid 13-character India Post tracking number, e.g. EE123456789IN.")); return render(); }
      done(app(b.dataset.awb), awb);
    }));
  },
});

/* ================================================================= STAFF: finance */
route("#/staff/finance", {
  auth: ["finance", "admin"],
  render: () => {
    const d = Store.get();
    return `<section class="card"><h1>${t("Payments & refunds")}</h1>
      <table class="grid"><thead><tr><th>${t("Payment ID")}</th><th>${t("Application ID")}</th><th>${t("Method")}</th><th>${t("Amount")}</th><th>${t("Status")}</th><th>${t("Settled")}</th></tr></thead><tbody>
      ${d.payments.map(p => `<tr><td>${esc(p.id)}${p.duplicate ? " " + badge(t("duplicate"), "amber") : ""}</td><td>${esc(p.appId)}</td><td>${esc(p.mode)}</td><td>${inr(p.amount)}</td>
        <td>${badge(p.status, p.status === "SUCCESS" ? "green" : "red")}</td><td>${fmt(p.settledAt)}</td></tr>`).join("") || `<tr><td colspan="6">${t("No payments yet.")}</td></tr>`}
      </tbody></table></section>
      <section class="card"><h2>${t("Refunds")}</h2><table class="grid"><thead><tr><th>${t("Application ID")}</th><th>${t("Amount")}</th><th>${t("Reason")}</th><th>${t("Due")}</th><th>${t("Status")}</th></tr></thead><tbody>
      ${d.refunds.map(r => `<tr><td>${esc(r.appId)}</td><td>${inr(r.amount)}</td><td>${esc(r.reason)}</td><td>${fmtDate(r.due)}</td><td>${esc(r.status)}</td></tr>`).join("") || `<tr><td colspan="5">${t("No refunds.")}</td></tr>`}
      </tbody></table></section>`;
  },
});

/* scheduled job: duplicate-debit auto refunds */
function runRefundJob() {
  const d = Store.get();
  d.refunds.filter(r => r.status === "Scheduled" && new Date(r.due) <= now()).forEach(r => {
    r.status = "Refunded"; const a = app(r.appId);
    if (a) notify("SMS", student(a.usn).mobile, `KVTU: Duplicate payment of ${inr(r.amount)} for ${a.id} refunded to your account.`);
  });
  Store.save();
}
