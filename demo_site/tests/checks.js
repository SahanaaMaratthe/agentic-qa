/* Verification harness: one check per planted bug.
   Each check sets up its own data, performs the action and returns what was observed.
   tests/test_practice_site.py runs every check in both builds and compares with the answer key. */
"use strict";
const H = {
  reset(mode) { Store.reset(false); Store.get().mode = mode; Store.save(); sessionStorage.clear(); FLASH = null; },
  student(usn) { Store.get().session = { kind: "student", usn }; Store.save(); },
  staff(u) { Store.get().session = { kind: "staff", user: u }; Store.save(); },
  wait(ms) { return new Promise(r => setTimeout(r, ms)); },
  async open(hash) { location.hash = hash; render(); await H.wait(60); },
  app(usn, status, items, delivery, extra) {
    const a = { id: "APP-TEST-" + rand(6), usn, status, items: items || [{ type: "CMC", qty: 1 }], delivery: delivery || "SELF",
      deliveryCharged: deliveryFee(delivery || "SELF"), address: "12, 4th Cross, Jayanagar, Bengaluru", country: "India",
      files: [{ name: "id.pdf", size: 1000, kind: "pdf", slot: "ID" }, { name: "grades.pdf", size: 1000, kind: "pdf", slot: "GRADE" }],
      resubmits: 0, created: now().toISOString(), ...(extra || {}) };
    if (status !== "DRAFT") a.lockedFee = feeOf(a).total;
    Store.get().apps.push(a); Store.save(); return a;
  },
  ticket(usn, category, extra) {
    const s = student(usn), start = now();
    const x = { id: "KVTU-GRV-TEST-" + rand(4), usn, college: s.college, mobile: s.mobile, email: s.email, category, sub: CATEGORIES[category][0],
      incident: "2026-01-10", description: "Test grievance description long enough.", files: [], status: "OPEN", tier: 1,
      owner: routeOwner(category, s.college), created: start.toISOString(), slaStart: start.toISOString(),
      slaDue: slaDue(start, 5).toISOString(), extensions: 0, reopens: 0, thread: [], ...(extra || {}) };
    Store.get().tickets.push(x); Store.save(); return x;
  },
  file(name, size, head, type) {
    const b = new Uint8Array(size); const h = typeof head === "string" ? new TextEncoder().encode(head) : head;
    b.set(h); return new File([b], name, { type: type || "application/pdf" });
  },
  set(id, v) { const el = $(id); el.value = v; el.dispatchEvent(new Event("input", { bubbles: true })); el.dispatchEvent(new Event("change", { bubbles: true })); },
  submit(id) { $(id).dispatchEvent(new Event("submit", { cancelable: true, bubbles: true })); },
  click(id) { $(id).click(); },
  text() { return document.getElementById("main").innerText; },
};
const PNG = [0x89, 0x50, 0x4E, 0x47, 0x0D, 0x0A, 0x1A, 0x0A];
const EICAR_STR = "X5O!P%@AP[4\\PZX54(P^)7CC)7}$EICAR-STANDARD-ANTIVIRUS-TEST-FILE!$H+H*";

const CHECKS = {
  /* ---------------- sign-in ---------------- */
  B01: async () => validUsnFormat("1KV21CS0011") && !!findStudentByUsn("1KV21CS0011"),
  B02: async () => { issueOtp("student:1KV21CS001", "9845012345", ""); const o = Store.get().otps.pop(); return Math.round((o.expires - now()) / 60000); },
  B03: async () => { issueOtp("s:x", "9845012345", ""); const c = Store.get().otps.at(-1).code; checkOtp("s:x", c); return checkOtp("s:x", c) === null; },
  B04: async () => { await H.open("#/login"); H.set("usn", "1KV21CS001"); H.set("dob", "1999-01-01"); H.set("email", "a@b.com"); H.set("mobile", "9845012345");
                     H.submit("f-login"); await H.wait(80); return location.hash === "#/otp"; },
  B05: async () => { H.student("1KV21CS001"); await H.open("#/student"); H.click("logout"); await H.wait(80); return Store.get().session !== null; },
  /* ---------------- cart ---------------- */
  B06: async () => { H.student("1KV21CS001"); const a = H.app("1KV21CS001", "DRAFT", []); await H.open("#/app/" + a.id); H.set("qty", "11"); H.submit("f-add"); await H.wait(50); return a.items.length; },
  B07: async () => { H.student("1KV21CS001"); const a = H.app("1KV21CS001", "DRAFT", []); await H.open("#/app/" + a.id); H.set("qty", "0"); H.submit("f-add"); await H.wait(50); return a.items.length; },
  B08: async () => { H.student("1KV21CS001"); const a = H.app("1KV21CS001", "DRAFT", [{ type: "CMC", qty: 1 }, { type: "MIGRATION", qty: 1 }]);
                     await H.open("#/app/" + a.id); document.querySelector("[data-remove='1']").click(); await H.wait(50); return $("total").textContent; },
  B09: async () => { H.student("1KV20EC045"); const a = H.app("1KV20EC045", "DRAFT", []); await H.open("#/app/" + a.id); H.set("doctype", "PDC"); H.set("qty", "1"); H.submit("f-add"); await H.wait(50); return a.items.length; },
  B10: async () => { H.student("1KV04CV001"); await H.open("#/apply"); await H.wait(50); return Store.get().apps.find(a => a.usn === "1KV04CV001").manualQueue; },
  /* ---------------- uploads ---------------- */
  B11: async () => { const a = H.app("1KV21CS001", "DRAFT", [], "SELF", { files: [] }); await handleFiles(a, [H.file("big.pdf", 5557452, "%PDF-1.4")], "ID"); return a.files.length; },
  B12: async () => { const a = H.app("1KV21CS001", "DRAFT", [], "SELF", { files: [] }); await handleFiles(a, [H.file("fake.pdf", 200, "plain text pretending")], "ID"); return a.files.length; },
  B13: async () => { const a = H.app("1KV21CS001", "DRAFT", [], "SELF", { files: [] });
                     const f = new File([new Uint8Array(PNG), EICAR_STR], "eicar.png", { type: "image/png" }); await handleFiles(a, [f], "GRADE"); return a.files.length; },
  B14: async () => { H.student("1KV21CS001"); const a = H.app("1KV21CS001", "DRAFT", [{ type: "CMC", qty: 1 }], "SELF", { files: [{ name: "id.pdf", size: 1, kind: "pdf", slot: "ID" }] });
                     await H.open("#/app/" + a.id); H.click("to-pay"); await H.wait(50); return a.status; },
  /* ---------------- fees ---------------- */
  B15: async () => deliveryFee("COURIER"),
  B16: async () => feeOf({ items: [{ type: "CMC", qty: 1 }, { type: "PDC", qty: 1 }], delivery: "SPEED" }).delivery,
  B17: async () => { H.student("1KV21CS001"); const a = H.app("1KV21CS001", "DRAFT", [{ type: "CMC", qty: 1 }]); await H.open("#/app/" + a.id);
                     document.querySelector("input[value=COURIER]").click(); document.querySelector("input[value=SELF]").click(); await H.wait(30); return feeOf(a).total; },
  B18: async () => { const a = H.app("1KV21CS001", "PAYMENT_PENDING", [{ type: "CMC", qty: 1 }]); Store.get().fees.CMC = 900; return payAmount(a); },
  B19: async () => { H.student("1KV21CS001"); const a = H.app("1KV21CS001", "PAYMENT_PENDING"), b = H.app("1KV21CS001", "PAYMENT_PENDING");
                     Store.get().waivers.push({ code: "WVR-AAAAAA", appId: a.id, used: false }); await H.open("#/app/" + b.id); H.set("wcode", "WVR-AAAAAA"); H.click("waive"); await H.wait(30); return b.status; },
  /* ---------------- payment ---------------- */
  B20: async () => { const a = H.app("1KV21CS001", "PAYMENT_PENDING"); const p = `${a.id}|${a.lockedFee}|FAILED|PAYX`; webhook(p, hmac(p)); return a.status; },
  B21: async () => { const a = H.app("1KV21CS001", "PAYMENT_PENDING"); webhook(`${a.id}|1|SUCCESS|PAYF`, "forged"); return a.status; },
  B22: async () => { H.student("1KV21CS001"); const a = H.app("1KV21CS001", "UNDER_VERIFICATION"); await H.open("#/app/" + a.id); return !!$("refund"); },
  B23: async () => { H.student("1KV21CS001"); const a = H.app("1KV21CS001", "PAYMENT_PENDING"); await H.open("#/gateway/" + a.id); H.set("outcome", "DUPLICATE"); H.click("paybtn");
                     await H.wait(50); const r = Store.get().refunds.at(-1); return Math.round((new Date(r.due) - now()) / 86400000); },
  B24: async () => { H.student("1KV21CS001"); const a = H.app("1KV21CS001", "PAYMENT_PENDING"); await H.open("#/gateway/" + a.id); document.querySelector("input[value=Card]").click();
                     H.click("paybtn"); await H.wait(800); await H.open("#/receipt/" + a.id); return /Payment method\s*Card/.test(H.text()) ? "Card" : (/Payment method\s*UPI/.test(H.text()) ? "UPI" : "?"); },
  B25: async () => { H.student("1KV21CS001"); const a = H.app("1KV21CS001", "PAYMENT_PENDING"); await H.open("#/gateway/" + a.id); H.click("paybtn"); H.click("paybtn");
                     await H.wait(800); return Store.get().payments.filter(p => p.appId === a.id).length; },
  /* ---------------- clerk / registrar / dispatch ---------------- */
  B26: async () => { H.staff("clerk"); const a = H.app("2MV19ME010", "UNDER_VERIFICATION"); await H.open("#/staff/clerk/" + a.id); H.click("query"); await H.wait(30); return a.status; },
  B27: async () => { H.student("2MV19ME010"); const a = H.app("2MV19ME010", "QUERY_RAISED", null, "SELF", { resubmits: 2, queryRemark: "x" }); await H.open("#/app/" + a.id); return !!$("resubmit"); },
  B28: async () => { H.staff("clerk"); const a = H.app("1KV20EC045", "UNDER_VERIFICATION", [{ type: "PDC", qty: 1 }]); await H.open("#/staff/clerk/" + a.id); H.click("approve"); await H.wait(30); return a.status; },
  B29: async () => { H.staff("clerk"); const a = H.app("2MV19ME010", "UNDER_VERIFICATION"); await H.open("#/staff/clerk/" + a.id); H.set("remark", "Grade card for semester 3 missing");
                     H.click("query"); await H.wait(30); return Store.get().outbox.filter(m => m.text.includes(a.id)).map(m => m.channel).sort().join("+"); },
  B30: async () => { H.staff("registrar"); const a = H.app("2MV19ME010", "APPROVED_FOR_SIGNING"); await H.open("#/staff/registrar"); H.set("dsc", "DSC-C3-2025");
                     document.querySelector(`[data-sign='${a.id}']`).click(); await H.wait(30); return a.status; },
  B31: async () => { const a = H.app("2MV19ME010", "SIGNED_&_PUBLISHED", null, "SELF", { qrHash: sha256("x" + rand(5)), signedAt: now().toISOString() });
                     Store.get().session = null; await H.open("#/verify?h=" + a.qrHash); await H.wait(30); return H.text().includes("2001-01-05"); },
  B32: async () => { const a = H.app("2MV19ME010", "SIGNED_&_PUBLISHED", null, "SELF", { qrHash: sha256("y" + rand(5)), signedAt: now().toISOString() });
                     await H.open("#/verify?h=" + a.qrHash.slice(0, 8) + "deadbeef"); await H.wait(30); return H.text().includes("AUTHENTIC"); },
  B33: async () => { H.staff("dispatch"); const a = H.app("2MV19ME010", "SIGNED_&_PUBLISHED", null, "SPEED"); await H.open("#/staff/dispatch");
                     H.set("awb-" + a.id, "EE12345678IN"); document.querySelector(`[data-awb='${a.id}']`).click(); await H.wait(30); return a.status; },
  B34: async () => { const a = H.app("2MV19ME010", "UNDER_VERIFICATION"); Store.get().session = null; await H.open("#/track"); H.set("tapp", a.id); H.set("tusn", "1KV21CS001");
                     H.submit("f-track"); await H.wait(30); return !$("track-out").innerText.includes("No application"); },
  B35: async () => timeline({ id: "none" }).match(/<li/g).length,
  /* ---------------- grievance intake ---------------- */
  B36: async () => { H.student("1KV21CS001"); await H.open("#/grievance/new"); H.set("g-cat", "College Infra"); H.set("g-date", "2026-01-10"); H.set("g-desc", "a".repeat(1800));
                     H.submit("f-grv"); await H.wait(30); return Store.get().tickets.length; },
  B37: async () => { H.student("1KV21CS001"); await H.open("#/grievance/new"); H.set("g-cat", "College Infra"); H.set("g-date", "2026-01-10"); H.set("g-desc", "The lab has no working computers for weeks.");
                     const dt = new DataTransfer(); for (let i = 0; i < 4; i++) dt.items.add(H.file(`e${i}.pdf`, 100, "%PDF-1.4")); $("g-files").files = dt.files;
                     H.submit("f-grv"); await H.wait(30); return Store.get().tickets.length; },
  B38: async () => { H.student("1KV21CS001"); await H.open("#/grievance/new"); H.set("g-cat", "College Infra"); H.set("g-date", "2099-01-01"); H.set("g-desc", "The lab has no working computers for weeks.");
                     H.submit("f-grv"); await H.wait(30); return Store.get().tickets.length; },
  B39: async () => { H.student("1KV21CS001"); await H.open("#/grievance/new"); H.set("g-cat", "College Infra"); H.set("g-date", "2026-01-10"); H.set("g-desc", "The lab has no working computers for weeks.");
                     H.submit("f-grv"); await H.wait(30); return Store.get().tickets[0].id.split("-").pop().length; },
  /* ---------------- routing & visibility ---------------- */
  B40: async () => routeOwner("Anti-Ragging", "KV").role,
  B41: async () => routeOwner("Revaluation", "KV").role,
  B42: async () => { const x = H.ticket("1KV21CS001", "College Infra"); return visibleTickets(staffUser("principal.mv")).includes(x); },
  /* ---------------- SLA ---------------- */
  B43: async () => { const fri = new Date("2026-11-20T10:00:00"); return slaDue(fri, 5).getDate(); },
  B44: async () => slaState({ status: "OPEN", slaDue: new Date(now().getTime() + 30 * HOUR).toISOString() }).cls,
  B45: async () => { const x = H.ticket("1KV21CS001", "College Infra", { tier: 2, slaDue: new Date(now().getTime() - HOUR).toISOString() }); runGrievanceJob(); return x.tier; },
  B46: async () => { H.staff("principal.kv"); const x = H.ticket("1KV21CS001", "College Infra", { extensions: 1 }); await H.open("#/staff/grievance/" + x.id);
                     H.set("o-text", "Waiting for contractor"); H.click("o-ext"); await H.wait(30); return x.extensions; },
  B47: async () => { H.staff("principal.kv"); const x = H.ticket("1KV21CS001", "College Infra"); await H.open("#/staff/grievance/" + x.id); H.set("o-text", "Library reopened");
                     H.click("o-resolve"); await H.wait(30); return Math.round((new Date(x.acceptDue) - now()) / 86400000); },
  B48: async () => { H.student("1KV21CS001"); const old = new Date(now().getTime() + 2 * HOUR).toISOString();
                     const x = H.ticket("1KV21CS001", "College Infra", { status: "PENDING_ACCEPTANCE", slaDue: old, acceptDue: new Date(now().getTime() + DAY).toISOString() });
                     await H.open("#/grievance/" + x.id); H.set("reopen-why", "Still closed"); H.click("reopen"); await H.wait(30); return new Date(x.slaDue) - now() > DAY; },
  B49: async () => { H.student("1KV21CS001"); const x = H.ticket("1KV21CS001", "College Infra", { status: "PENDING_ACCEPTANCE", reopens: 1, acceptDue: new Date(now().getTime() + DAY).toISOString() });
                     await H.open("#/grievance/" + x.id); H.set("reopen-why", "Still not fixed"); H.click("reopen"); await H.wait(30); return x.tier; },
  B50: async () => { H.student("1KV21CS001"); const x = H.ticket("1KV21CS001", "College Infra", { status: "PENDING_ACCEPTANCE", acceptDue: new Date(now().getTime() + DAY).toISOString() });
                     await H.open("#/grievance/" + x.id); if ($("rating-n")) H.set("rating-n", "0"); H.click("satisfied"); await H.wait(30); return x.rating ?? null; },
  B51: async () => { H.staff("principal.kv"); const x = H.ticket("1KV21CS001", "College Infra", { thread: [{ ts: now().toISOString(), by: "principal.kv", who: "officer", text: "Checked" }] });
                     await H.open("#/staff/grievance/" + x.id); return !!document.querySelector("[data-del]"); },
  /* ---------------- language & accessibility ---------------- */
  B52: async () => { H.student("1KV21CS001"); Store.get().lang = "kn"; Store.save(); await H.open("#/grievance/new"); const r = document.querySelector("label[for=g-date]").textContent; Store.get().lang = "en"; Store.save(); return r; },
  B53: async () => { H.student("1KV21CS001"); await H.open("#/grievance/new"); H.set("g-desc", "Typed before switching language"); H.click("lang"); await H.wait(30);
                     const v = $("g-desc").value; Store.get().lang = "en"; Store.save(); return v; },
  B54: async () => { await H.open("#/otp"); return !!document.querySelector("label[for=otp]"); },
  /* ---------------- MIS ---------------- */
  B55: async () => { H.staff("admin"); H.ticket("1KV21CS001", "College Infra"); H.ticket("2MV19ME010", "Exam/Results", { tier: 2 }); await H.open("#/mis");
                     return Number(document.querySelector(".metric b").textContent); },
  B56: async () => { H.staff("principal.kv"); H.ticket("1KV21CS001", "College Infra"); H.ticket("2MV19ME010", "College Infra"); await H.open("#/mis");
                     return Number(document.querySelector(".metric b").textContent); },
  /* ---------------- security ---------------- */
  B57: async () => { Store.get().session = null; await H.open("#/staff/login"); H.set("user", "clerk"); H.set("pass", "Demo@123"); $("remember").checked = true;
                     H.submit("f-staff"); await H.wait(50); return !!Store.get().session; },
  B58: async () => { H.student("1KV21CS001"); await H.open("#/staff/clerk"); return H.text().includes("Scrutiny workbench"); },
  B59: async () => { window.__xss = 0; H.staff("principal.kv");
                     const x = H.ticket("1KV21CS001", "College Infra", { description: 'Broken lab <img src="x" onerror="window.__xss=1">' });
                     await H.open("#/staff/grievance/" + x.id); await H.wait(300); return window.__xss === 1; },
};
