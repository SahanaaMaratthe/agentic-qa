/* KVTU practice portal: fee master, MIS dashboard, public pages, QA panel. */
"use strict";

/* ---------------------------------------------------------------- public fee schedule */
route("#/fees", {
  render: () => {
    const d = Store.get();
    return `<section class="card narrow"><h1>${t("Fee schedule")}</h1>
      <table class="grid"><thead><tr><th>${t("Document")}</th><th>${t("Fee per copy")}</th></tr></thead><tbody>
      ${Object.keys(DOCS).map(k => `<tr><td>${docName(k)}</td><td>${inr(d.fees[k])}</td></tr>`).join("")}</tbody></table>
      <table class="grid"><thead><tr><th>${t("Delivery")}</th><th>${t("Charge per application")}</th></tr></thead><tbody>
      ${Object.entries(DELIVERY).map(([k, l]) => `<tr><td>${t(l)}</td><td>${inr(d.delivery[k])}</td></tr>`).join("")}</tbody></table>
      <p class="muted">${t("Total fee = sum of (fee per copy × copies) + one delivery charge. The fee is fixed when you click Proceed to Pay.")}</p></section>`;
  },
});

route("#/about", {
  render: () => `<section class="card"><h1>${t("About this practice portal")}</h1>
    <p>${t("Kaveri Valley Technological University (KVTU) is fictional. This portal implements the eDDTS and Grievance Redressal requirements from the practice BRD / BRS so that QA teams can practise testing safely.")}</p>
    <p>${t("Names differ from the sample documents: VTU → KVTU, ticket prefix VTU-GRV → KVTU-GRV. Requirement IDs (FR-EDD-01, BR-GRV-02 ...) are unchanged.")}</p></section>`,
});

/* ---------------------------------------------------------------- admin: fee master */
route("#/admin/fees", {
  auth: ["admin"],
  render: () => {
    const d = Store.get();
    return `<section class="card narrow"><h1>${t("Fee master")}</h1>
      <form id="f-fees">${Object.keys(DOCS).map(k => field(`fee-${k}`, DOCS[k], `<input id="fee-${k}" type="number" min="0" step="1" value="${d.fees[k]}">`)).join("")}
      ${Object.entries(DELIVERY).map(([k, l]) => field(`del-${k}`, l, `<input id="del-${k}" type="number" min="0" step="1" value="${d.delivery[k]}">`)).join("")}
      <p class="muted">${t("New fees apply to applications that have not yet reached Proceed to Pay. Fees already fixed at checkout do not change.")}</p>
      <button class="btn primary">${t("Save fees")}</button></form></section>`;
  },
  after: () => on("f-fees", "submit", e => {
    e.preventDefault();
    const d = Store.get(), before = JSON.stringify({ fees: d.fees, delivery: d.delivery });
    for (const k of Object.keys(DOCS)) d.fees[k] = Math.max(0, Math.round(Number(val(`fee-${k}`)) || 0));
    for (const k of Object.keys(DELIVERY)) d.delivery[k] = Math.max(0, Math.round(Number(val(`del-${k}`)) || 0));
    Store.save(); audit("FEES", "master", staffMe().user, before, JSON.stringify({ fees: d.fees, delivery: d.delivery }), "Fee master updated");
    flash("ok", t("Fees saved.")); render();
  }),
});

/* ---------------------------------------------------------------- MIS dashboard: FR-GRV-05 */
route("#/mis", {
  auth: ["clerk", "registrar", "dispatch", "principal", "regional", "ombudsperson", "statcell", "finance", "admin"],
  render: () => {
    const d = Store.get(), u = staffMe();
    const scoped = u.role === "principal" && !bug("B56");                                                     // B56: not role-scoped
    const tks = d.tickets.filter(x => !scoped || x.college === u.college);
    const isOpen = x => ["OPEN", "INFO_REQUESTED"].includes(x.status) && (!bug("B55") || x.tier === 1);       // B55: escalated not counted
    const breached = tks.filter(x => ["OPEN", "INFO_REQUESTED"].includes(x.status) && new Date(x.slaDue) < now());
    const appRoles = ["clerk", "registrar", "dispatch", "finance", "admin"].includes(u.role);
    const byStatus = {}; d.apps.forEach(a => byStatus[a.status] = (byStatus[a.status] || 0) + 1);
    const byCat = {}; tks.forEach(x => byCat[x.category] = (byCat[x.category] || 0) + 1);
    const card = (l, v, cls) => `<div class="metric ${cls || ""}"><span>${t(l)}</span><b>${v}</b></div>`;
    window.__misRows = tks.map(x => [x.id, x.college, x.category, x.status, x.tier, x.slaDue]);
    return `<section class="card"><h1>${t("MIS dashboard")}</h1>
      <p class="muted">${scoped ? `${t("Scope")}: ${esc(d.colleges[u.college])}` : t("Scope: whole university")}</p>
      <h2>${t("Grievances")}</h2>
      <div class="metrics">${card("Open grievances", tks.filter(isOpen).length)}${card("Awaiting student confirmation", tks.filter(x => x.status === "PENDING_ACCEPTANCE").length)}
        ${card("Closed", tks.filter(x => x.status === "CLOSED").length)}${card("SLA breached", breached.length, breached.length ? "red" : "")}</div>
      <table class="grid"><thead><tr><th>${t("Category")}</th><th>${t("Grievances")}</th></tr></thead><tbody>
        ${Object.keys(CATEGORIES).map(c => `<tr><td>${t(c)}</td><td>${byCat[c] || 0}</td></tr>`).join("")}</tbody></table>
      ${appRoles ? `<h2>${t("Document applications")}</h2><div class="metrics">${Object.keys(STATUS_LABEL).map(s => card(STATUS_LABEL[s], byStatus[s] || 0)).join("")}</div>` : ""}
      <div class="actions no-print"><button id="csv" class="btn">${t("Export (CSV for Excel)")}</button><button class="btn" onclick="window.print()">${t("Export PDF (print)")}</button></div>
    </section>`;
  },
  after: () => on("csv", "click", () => {
    const rows = [["Ticket ID", "College", "Category", "Status", "Tier", "SLA due"], ...window.__misRows];
    const csv = rows.map(r => r.map(v => `"${String(v).replace(/"/g, '""')}"`).join(",")).join("\r\n");
    download("kvtu_mis.csv", new Blob(["﻿" + csv], { type: "text/csv" }));
  }),
});

function download(name, blob) {
  const a = document.createElement("a"); a.href = URL.createObjectURL(blob); a.download = name;
  document.body.appendChild(a); a.click(); setTimeout(() => { URL.revokeObjectURL(a.href); a.remove(); }, 500);
}

/* ================================================================= QA PANEL */
route("#/qa", {
  render: p => {
    const d = Store.get(), tab = p.tab || "mode";
    const tabs = [["mode", "Mode & data"], ["clock", "Clock"], ["outbox", "SMS / e-mail inbox"], ["accounts", "Practice accounts"],
                  ["files", "Test files"], ["gateway", "Payment gateway tools"]];
    return `<section class="card qa"><h1>${t("QA panel")}</h1>
      <p class="muted">${t("Tools for testers. In a real system these would not exist.")}</p>
      <nav class="tabs">${tabs.map(([k, l]) => `<a href="#/qa?tab=${k}" class="${tab === k ? "active" : ""}">${t(l)}</a>`).join("")}</nav>
      ${({ mode: qaMode, clock: qaClock, outbox: qaOutbox, accounts: qaAccounts, files: qaFiles, gateway: qaGateway })[tab](d)}</section>`;
  },
  after: p => {
    const d = Store.get();
    document.querySelectorAll("input[name=mode]").forEach(r => r.addEventListener("change", () => {
      d.mode = r.value; Store.save(); flash("ok", `${t("Mode")}: ${r.value === "buggy" ? t("practice build (with bugs)") : t("reference build (correct)")}`); render();
    }));
    on("reset", "click", () => { if (confirm("Delete all applications, grievances and messages?")) { Store.reset(true); flash("ok", t("All data reset.")); render(); } });
    on("samples", "click", () => { seedSamples(); flash("ok", t("Sample applications and grievances loaded.")); render(); });
    document.querySelectorAll("[data-clock]").forEach(b => b.addEventListener("click", () => {
      const v = b.dataset.clock;
      if (v === "reset") d.clockOffset = 0;
      else if (v === "wd") { const target = addWorkingDays(now(), 1); d.clockOffset += target - now(); }
      else d.clockOffset += Number(v);
      Store.save(); render();
    }));
    on("clear-outbox", "click", () => { d.outbox = []; Store.save(); render(); });
    document.querySelectorAll("[data-file]").forEach(b => b.addEventListener("click", () => makeTestFile(b.dataset.file)));
    on("forge", "click", () => {
      const a = app($("forge-app").value); if (!a) return;
      const payload = `${a.id}|1|SUCCESS|PAYFORGED${rand(6)}`;
      const res = webhook(payload, "0000forged-signature");
      $("forge-out").innerHTML = `<p class="flash ${res === "ok" ? "error" : "ok"}">${t("Portal response")}: <b>${esc(res)}</b>. ${t("Application status now")}: ${statusBadge(a.status)}</p>`;
    });
  },
});

function qaMode(d) {
  return `<h2>${t("Build under test")}</h2>
    <fieldset class="radios"><label><input type="radio" name="mode" value="buggy" ${d.mode === "buggy" ? "checked" : ""}> <b>${t("Practice build")}</b>: ${t("contains planted bugs")}</label>
    <label><input type="radio" name="mode" value="correct" ${d.mode === "correct" ? "checked" : ""}> <b>${t("Reference build")}</b>: ${t("behaves as the BRS says")}</label></fieldset>
    <p class="muted">${t("A good test case fails on the practice build and passes on the reference build. The answer key (ANSWER_KEY.md in the demo_site folder) lists every planted bug: open it only after testing.")}</p>
    <h2>${t("Data")}</h2>
    <div class="actions"><button id="samples" class="btn">${t("Load sample applications & grievances")}</button>
      <button id="reset" class="btn danger">${t("Reset all data")}</button></div>
    <p class="muted small">${d.apps.length} ${t("applications")} · ${d.tickets.length} ${t("grievances")} · ${d.outbox.length} ${t("messages")}</p>`;
}
function qaClock() {
  return `<h2>${t("System clock")}</h2><p>${t("Now")}: <b>${fmt(now())}</b> (${now().toLocaleDateString("en-IN", { weekday: "long" })})</p>
    <p class="muted">${t("Move time forward to test OTP expiry, SLA timers, escalation, auto-close and refunds. Scheduled jobs run on every page load.")}</p>
    <div class="actions">${[["600000", "+10 minutes"], ["3600000", "+1 hour"], ["86400000", "+1 day"], ["wd", "+1 working day"],
      ["432000000", "+5 days"], ["604800000", "+7 days"], ["reset", "Back to real time"]].map(([v, l]) => `<button class="btn" data-clock="${v}">${t(l)}</button>`).join("")}</div>`;
}
function qaOutbox(d) {
  return `<h2>${t("Messages sent by the portal")}</h2><p class="muted">${t("Mock SMS and e-mail gateway: newest first.")}</p>
    <table class="grid"><thead><tr><th>${t("Time")}</th><th>${t("Channel")}</th><th>${t("To")}</th><th>${t("Message")}</th></tr></thead><tbody>
    ${d.outbox.slice(0, 80).map(m => `<tr><td>${fmt(m.ts)}</td><td>${esc(m.channel)}</td><td>${esc(m.to)}</td><td>${esc(m.text)}</td></tr>`).join("") || `<tr><td colspan="4">${t("No messages yet.")}</td></tr>`}
    </tbody></table><button id="clear-outbox" class="btn">${t("Clear inbox")}</button>`;
}
function qaAccounts(d) {
  return `<h2>${t("Students")}</h2><table class="grid"><thead><tr><th>USN</th><th>${t("Name")}</th><th>${t("Date of birth")}</th><th>${t("Mobile")}</th><th>${t("Notes")}</th></tr></thead><tbody>
    ${d.students.map(s => `<tr><td class="mono">${s.usn}</td><td>${esc(s.name)}</td><td>${s.dob}</td><td>${s.mobile}</td>
      <td>${s.cleared ? t("Exams cleared") : t("Exams NOT cleared")}${s.legacy ? " · " + t("pre-2005 legacy USN") : ""} · ${esc(d.colleges[s.college])}</td></tr>`).join("")}</tbody></table>
    <h2>${t("Staff")}</h2><p>${t("Password for every staff account")}: <b class="mono">${d.staffPassword}</b> · ${t("then the OTP from the inbox")}</p>
    <table class="grid"><thead><tr><th>${t("Username")}</th><th>${t("Role")}</th><th>${t("Name")}</th></tr></thead><tbody>
    ${d.staff.map(s => `<tr><td class="mono">${s.user}</td><td>${t(ROLE_LABEL[s.role])}${s.college ? " · " + s.college : ""}</td><td>${esc(s.name)}</td></tr>`).join("")}</tbody></table>`;
}
function qaFiles() {
  const files = [["valid.pdf", "Small valid PDF"], ["grade_card.png", "Small valid PNG image"], ["photo_id.jpg", "Small valid JPG image"],
    ["exactly_5MB.pdf", "PDF of exactly 5 MB (5,242,880 bytes)"], ["5.3MB.pdf", "PDF of 5.3 MB"], ["5.8MB.pdf", "PDF of 5.8 MB"],
    ["fake.pdf", "Text file renamed to .pdf"], ["eicar.pdf", "PDF containing the EICAR antivirus test string"],
    ["eicar.png", "PNG containing the EICAR antivirus test string"]];
  return `<h2>${t("Download test files")}</h2><p class="muted">${t("Use these to test upload rules. The EICAR string is a harmless industry-standard antivirus test pattern.")}</p>
    <ul class="files">${files.map(([n, l]) => `<li><button class="link" data-file="${n}">${n}</button> · ${t(l)}</li>`).join("")}</ul>`;
}
function qaGateway(d) {
  const pend = d.apps.filter(a => a.status === "PAYMENT_PENDING");
  return `<h2>${t("Forged payment confirmation")}</h2>
    <p class="muted">${t("Sends a fake 'payment SUCCESS' callback for ₹1 with an invalid signature, as an attacker would. A correct portal must reject it.")}</p>
    ${pend.length ? `${field("forge-app", "Application awaiting payment", `<select id="forge-app">${pend.map(a => `<option>${esc(a.id)}</option>`).join("")}</select>`)}
      <button id="forge" class="btn danger">${t("Send forged callback")}</button><div id="forge-out"></div>` : `<p>${t("Create an application and click Proceed to Pay first.")}</p>`}`;
}

function makeTestFile(name) {
  const EIC = "X5O!P%@AP[4\\PZX54(P^)7CC)7}$EICAR-STANDARD-ANTIVIRUS-TEST-FILE!$H+H*";
  const pdf = body => `%PDF-1.4\n1 0 obj<<>>endobj\n% ${body}\n%%EOF\n`;
  const png = [0x89, 0x50, 0x4E, 0x47, 0x0D, 0x0A, 0x1A, 0x0A, 0, 0, 0, 13, 0x49, 0x48, 0x44, 0x52, 0, 0, 0, 1, 0, 0, 0, 1, 8, 6, 0, 0, 0, 0x1F, 0x15, 0xC4, 0x89,
    0, 0, 0, 13, 0x49, 0x44, 0x41, 0x54, 0x78, 0x9C, 0x63, 0xF8, 0xCF, 0xC0, 0xF0, 0x1F, 0, 5, 0, 1, 0xFF, 0x89, 0x99, 0x3D, 0x1D, 0, 0, 0, 0, 0x49, 0x45, 0x4E, 0x44, 0xAE, 0x42, 0x60, 0x82];
  const sized = (n, head) => { const b = new Uint8Array(n); const h = new TextEncoder().encode(head); b.set(h); b.fill(0x20, h.length); return b; };
  const files = {
    "valid.pdf": () => new Blob([pdf("valid practice document")], { type: "application/pdf" }),
    "grade_card.png": () => new Blob([new Uint8Array(png)], { type: "image/png" }),
    "photo_id.jpg": () => { const c = document.createElement("canvas"); c.width = c.height = 40; const g = c.getContext("2d"); g.fillStyle = "#4a7"; g.fillRect(0, 0, 40, 40);
      return new Blob([Uint8Array.from(atob(c.toDataURL("image/jpeg").split(",")[1]), ch => ch.charCodeAt(0))], { type: "image/jpeg" }); },
    "exactly_5MB.pdf": () => new Blob([sized(5 * 1024 * 1024, pdf("5MB"))], { type: "application/pdf" }),
    "5.3MB.pdf": () => new Blob([sized(5557452, pdf("5.3MB"))], { type: "application/pdf" }),          // between 5 MB and 5.5 MB
    "5.8MB.pdf": () => new Blob([sized(Math.round(5.8 * 1024 * 1024), pdf("5.8MB"))], { type: "application/pdf" }),
    "fake.pdf": () => new Blob(["This is a plain text file pretending to be a PDF."], { type: "application/pdf" }),
    "eicar.pdf": () => new Blob([pdf(EIC)], { type: "application/pdf" }),
    "eicar.png": () => new Blob([new Uint8Array(png), EIC], { type: "image/png" }),
  };
  download(name, files[name]());
}

/* sample data in every state, so testers don't have to click through each flow */
function seedSamples() {
  const d = Store.get(), t0 = now();
  const mk = (usn, status, items, delivery, extra) => {
    const a = { id: `APP-${t0.getFullYear()}-${rand(6)}`, usn, status: "DRAFT", items, delivery, deliveryCharged: deliveryFee(delivery),
      address: delivery === "SELF" ? "" : "12, 4th Cross, Jayanagar, Bengaluru 560011", country: delivery === "COURIER" ? "Germany" : "India",
      files: [{ name: "aadhaar.pdf", size: 220000, kind: "pdf", slot: "ID" }, { name: "grade_cards.pdf", size: 1200000, kind: "pdf", slot: "GRADE" }],
      resubmits: 0, created: t0.toISOString(), ...extra };
    d.apps.push(a); audit("APP", a.id, usn, "-", "DRAFT", "Sample");
    const path = ["PAYMENT_PENDING", "UNDER_VERIFICATION", "APPROVED_FOR_SIGNING", "SIGNED_&_PUBLISHED", "DISPATCHED"];
    for (const st of path) {
      if (st === "PAYMENT_PENDING") a.lockedFee = feeOf(a).total;
      if (st === "UNDER_VERIFICATION") { const pid = newPaymentId(); d.payments.push({ id: pid, appId: a.id, gatewayRef: "SBI" + rand(10, "0123456789"), mode: "UPI", amount: a.lockedFee, status: "SUCCESS", settledAt: t0.toISOString() }); a.paymentId = pid; }
      if (st === "SIGNED_&_PUBLISHED") { a.signedAt = t0.toISOString(); a.qrHash = sha256(`${a.id}|${a.usn}|sample|${a.signedAt}`); }
      if (st === "DISPATCHED" && delivery !== "SELF") a.awb = "EE" + rand(9, "0123456789") + "IN";
      audit("APP", a.id, "sample", a.status, st, "Sample data"); a.status = st;
      if (st === status) break;
    }
    return a;
  };
  mk("1KV21CS001", "PAYMENT_PENDING", [{ type: "TRANSCRIPT", qty: 3 }], "COURIER");
  mk("2MV19ME010", "UNDER_VERIFICATION", [{ type: "PDC", qty: 1 }, { type: "CMC", qty: 2 }], "SPEED");
  mk("1KV21CS001", "APPROVED_FOR_SIGNING", [{ type: "MIGRATION", qty: 1 }], "SELF");
  mk("2MV19ME010", "SIGNED_&_PUBLISHED", [{ type: "TRANSCRIPT", qty: 2 }], "SPEED");
  mk("1KV21CS001", "DISPATCHED", [{ type: "CMC", qty: 1 }], "SPEED");
  const tk = (usn, category, sub, desc, ageDays, tierOverride) => {
    const s = student(usn), start = new Date(t0.getTime() - ageDays * DAY), n = Store.nextSeq("grv");
    const x = { id: `KVTU-GRV-${t0.getFullYear()}-${String(n).padStart(bug("B39") ? 4 : 5, "0")}`, usn, college: s.college, mobile: s.mobile, email: s.email,
      category, sub, incident: start.toISOString().slice(0, 10), description: desc, files: [], status: "OPEN", tier: tierOverride || 1,
      owner: routeOwner(category, s.college), created: start.toISOString(), slaStart: start.toISOString(), slaDue: slaDue(start, 5).toISOString(),
      extensions: 0, reopens: 0, thread: [] };
    d.tickets.push(x); audit("GRV", x.id, usn, "-", "OPEN", "Sample");
    return x;
  };
  tk("1KV21CS001", "College Infra", "Library", "The central library has been closed on weekdays for three weeks, so we cannot borrow reference books.", 1);
  tk("2MV19ME010", "College Infra", "Hostel", "Drinking water in the men's hostel block B has not been available for four days.", 2);
  tk("1KV20EC045", "Exam/Results", "Result withheld", "My semester 5 result has been shown as withheld for two months without any reason given.", 3);
  tk("3PE22AI007", "Anti-Ragging", "Harassment", "Senior students have been forcing first-year students to do their assignments at night.", 0);
  tk("2MV19ME010", "Revaluation", "Revaluation result delayed", "I applied for revaluation of Thermodynamics 45 days ago and have no result yet.", 4);
  Store.save();
}
