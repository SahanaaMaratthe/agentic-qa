/* KVTU practice portal: router, layout, sign-in. */
"use strict";

const Routes = {};
const ROLE_LABEL = { clerk: "Exam Clerk", registrar: "Registrar (Evaluation)", dispatch: "Dispatch Clerk", principal: "College Principal",
  regional: "Regional Director", ombudsperson: "Ombudsperson", statcell: "Statutory Cell (Anti-Ragging)", finance: "Finance Officer",
  admin: "ICT Administrator" };          // "#/path" -> {render(params) -> html, after(params), auth: "student"|role list|undefined}
function route(path, def) { Routes[path] = def; }

/* ---- small UI helpers ------------------------------------------------------- */
let FLASH = null;
function flash(kind, msg) { FLASH = { kind, msg }; }
function $(id) { return document.getElementById(id); }
function on(id, ev, fn) { const el = $(id); if (el) el.addEventListener(ev, fn); }
function go(hash) { if (location.hash === hash) render(); else location.hash = hash; }
function session() { return Store.get().session; }
function me() { const s = session(); return s && s.kind === "student" ? student(s.usn) : null; }
function staffMe() { const s = session(); return s && s.kind === "staff" ? staffUser(s.user) : null; }
function val(id) { const el = $(id); return el ? el.value.trim() : ""; }
function field(id, label, input, help) {
  return `<div class="field"><label for="${id}">${t(label)}</label>${input}${help ? `<div class="help">${help}</div>` : ""}</div>`;
}
function badge(text, cls) { return `<span class="badge ${cls || ""}">${esc(text)}</span>`; }

/* ---- layout ------------------------------------------------------------------ */
function nav() {
  const s = session(), links = [];
  if (!s) {
    links.push(["#/", "Home"], ["#/track", "Track application"], ["#/verify", "Verify certificate"],
               ["#/fees", "Fee schedule"], ["#/login", "Student login"], ["#/staff/login", "Staff login"]);
  } else if (s.kind === "student") {
    links.push(["#/student", "Dashboard"], ["#/apply", "New document request"], ["#/grievance/new", "Lodge grievance"],
               ["#/track", "Track application"]);
  } else {
    const r = staffMe().role;
    if (r === "clerk") links.push(["#/staff/clerk", "Scrutiny workbench"]);
    if (r === "registrar") links.push(["#/staff/registrar", "Signing desk"], ["#/staff/grievances", "Grievance inbox"]);
    if (r === "dispatch") links.push(["#/staff/dispatch", "Dispatch desk"]);
    if (["principal", "regional", "ombudsperson", "statcell"].includes(r)) links.push(["#/staff/grievances", "Grievance inbox"]);
    if (r === "finance") links.push(["#/staff/finance", "Payments & refunds"]);
    if (r === "admin") links.push(["#/admin/fees", "Fee master"], ["#/staff/grievances", "Grievance inbox"]);
    links.push(["#/mis", "MIS dashboard"]);
  }
  const cur = location.hash || "#/";
  return links.map(([h, l]) => `<a href="${h}" class="${cur === h ? "active" : ""}">${t(l)}</a>`).join("");
}

function layout(body) {
  const d = Store.get(), s = session();
  const who = s ? (s.kind === "student" ? `${esc(me().name)} (${esc(s.usn)})` : `${esc(staffMe().name)} · ${t(ROLE_LABEL[staffMe().role])}`) : "";
  const f = FLASH; FLASH = null;
  return `
  <div class="practice-banner" role="note">${t("PRACTICE SYSTEM: a fictional university portal for QA training. Not a real university.")}</div>
  <header class="top">
    <div class="brand"><div class="logo" aria-hidden="true">KV</div>
      <div><div class="uni">${t("Kaveri Valley Technological University")}</div>
      <div class="sub">${t("Student Services Portal · eDDTS & Grievance Redressal")}</div></div></div>
    <div class="top-right">
      <button id="lang" class="lang" aria-label="${t("Switch language")}">${d.lang === "en" ? "ಕನ್ನಡ" : "English"}</button>
      ${s ? `<span class="who">${who}</span><button id="logout" class="link">${t("Sign out")}</button>` : ""}
    </div>
  </header>
  <nav class="main-nav" aria-label="${t("Main menu")}">${nav()}</nav>
  <main id="main" tabindex="-1">
    ${f ? `<div class="flash ${f.kind}" role="${f.kind === "error" ? "alert" : "status"}">${f.msg}</div>` : ""}
    ${body}
  </main>
  <footer class="foot">
    <span>${t("System time")}: <b id="clock">${fmt(now())}</b></span>
    <span>Build 2026.11 · <span class="mode-${d.mode}">${d.mode === "buggy" ? "practice build" : "reference build"}</span></span>
    <a href="#/qa">${t("QA panel")}</a>
  </footer>`;
}

/* ---- render loop --------------------------------------------------------------- */
function parseHash() {
  const h = location.hash || "#/";
  const [path, qs] = h.split("?");
  const params = Object.fromEntries(new URLSearchParams(qs || ""));
  if (Routes[path]) return { def: Routes[path], params };
  for (const p of Object.keys(Routes)) {                       // routes with :id
    const re = new RegExp("^" + p.replace(/:[a-z]+/g, "([^/]+)") + "$");
    const m = path.match(re);
    if (m) return { def: Routes[p], params: { ...params, id: decodeURIComponent(m[1]) } };
  }
  return { def: Routes["#/404"], params };
}

function allowed(def) {
  if (!def.auth) return true;
  const s = session();
  if (!s) return false;
  if (def.auth === "student") return s.kind === "student";
  if (s.kind !== "staff") return bug("B58") && def.auth !== "admin-only";     // B58: staff pages open to students via URL
  return def.auth.includes(staffMe().role);
}

function render() {
  runScheduler();
  const { def, params } = parseHash();
  let body;
  if (!allowed(def)) {
    body = `<section class="card"><h1>${t("Access denied")}</h1><p>${t("Please sign in with an account that is allowed to open this page.")}</p>
            <a class="btn" href="${def.auth === "student" ? "#/login" : "#/staff/login"}">${t("Sign in")}</a></section>`;
  } else {
    try { body = def.render(params); } catch (e) { console.error(e); body = `<section class="card error-card"><h1>${t("Something went wrong")}</h1><pre>${esc(e.message)}</pre></section>`; }
  }
  document.getElementById("app").innerHTML = layout(body);
  on("lang", "click", toggleLang);
  on("logout", "click", () => {
    if (!bug("B05")) { Store.get().session = null; Store.save(); }                    // B05: session survives sign-out
    flash("ok", t("You have signed out.")); go("#/");
  });
  if (allowed(def) && def.after) def.after(params);
  document.title = "KVTU Practice Portal";
}

/* language toggle: the reference build keeps whatever the user has typed (B53 loses it) */
function toggleLang() {
  const keep = {};
  if (!bug("B53")) document.querySelectorAll("#main input, #main textarea, #main select").forEach(el => {
    if (el.id && el.type !== "file") keep[el.id] = el.type === "checkbox" ? el.checked : el.value;
  });
  const d = Store.get(); d.lang = d.lang === "en" ? "kn" : "en"; Store.save();
  render();
  for (const [id, v] of Object.entries(keep)) {
    const el = $(id); if (!el) continue;
    if (el.type === "checkbox") el.checked = v; else el.value = v;
    el.dispatchEvent(new Event("input", { bubbles: true }));
  }
}

window.addEventListener("hashchange", render);
window.addEventListener("DOMContentLoaded", render);
setInterval(() => { const c = $("clock"); if (c) c.textContent = fmt(now()); }, 30000);

/* ===================================================================== pages */
route("#/", {
  render: () => `
  <section class="hero card">
    <h1>${t("Welcome to the Student Services Portal")}</h1>
    <p>${t("Apply for academic documents, track your application, and lodge grievances, all online.")}</p>
    <div class="tiles">
      <a class="tile" href="#/login"><b>${t("Academic documents (eDDTS)")}</b><span>${t("Transcripts, Provisional Degree Certificate, Marks Card, Migration")}</span></a>
      <a class="tile" href="#/login"><b>${t("Grievance Redressal")}</b><span>${t("Exam, marks card, revaluation, college facilities, anti-ragging")}</span></a>
      <a class="tile" href="#/track"><b>${t("Track application")}</b><span>${t("No login needed: Application ID + USN")}</span></a>
      <a class="tile" href="#/verify"><b>${t("Verify certificate")}</b><span>${t("Check a QR-coded certificate is authentic")}</span></a>
    </div>
  </section>`,
});

route("#/404", { render: () => `<section class="card"><h1>${t("Page not found")}</h1><a href="#/">${t("Home")}</a></section>` });

/* ---- student sign-in: Step 1.1 / FR-EDD-01 ---------------------------------------- */
function normUsn(raw) { return String(raw || "").trim().toUpperCase(); }
function validUsnFormat(u) {
  return bug("B01") ? /^[1-4][A-Z]{2}\d{2}[A-Z]{2}\d{3}/.test(u)            // B01: no end anchor -> 11+ chars accepted
                    : /^[1-4][A-Z]{2}\d{2}[A-Z]{2}\d{3}$/.test(u);
}
function findStudentByUsn(u) {
  const d = Store.get();
  return bug("B01") ? d.students.find(s => u.startsWith(s.usn)) : d.students.find(s => s.usn === u);
}

route("#/login", {
  render: () => `
  <section class="card narrow">
    <h1>${t("Student sign in")}</h1>
    <p class="muted">${t("Enter your University Seat Number (USN) and details. We will send a One-Time Password (OTP) to your mobile and e-mail.")}</p>
    <form id="f-login" novalidate>
      ${field("usn", "University Seat Number (USN)", `<input id="usn" autocomplete="off" maxlength="14" placeholder="1KV21CS001">`, t("10 characters, e.g. 1KV21CS001"))}
      ${field("dob", "Date of birth", `<input id="dob" type="date">`)}
      ${field("email", "E-mail", `<input id="email" type="email">`)}
      ${field("mobile", "Mobile number", `<input id="mobile" inputmode="numeric" maxlength="10">`)}
      <button class="btn primary" type="submit">${t("Send OTP")}</button>
    </form>
  </section>`,
  after: () => on("f-login", "submit", e => {
    e.preventDefault();
    const u = normUsn(val("usn")), dob = val("dob"), email = val("email"), mobile = val("mobile");
    if (!validUsnFormat(u)) { flash("error", t("Invalid USN format. A USN has 10 characters, e.g. 1KV21CS001.")); return render(); }
    const s = findStudentByUsn(u);
    if (!s) { flash("error", t("USN not found in University records.")); return render(); }
    if (!bug("B04") && s.dob !== dob) {                                       // B04: date of birth never checked
      flash("error", t("The details you entered do not match our records."));
      return render();
    }
    if (!/^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(email) || !/^[6-9]\d{9}$/.test(mobile)) {
      flash("error", t("Enter a valid e-mail and a 10-digit mobile number.")); return render();
    }
    issueOtp("student:" + s.usn, mobile, email);
    sessionStorage.setItem("pendingUsn", s.usn);
    go("#/otp");
  }),
});

function issueOtp(subject, mobile, email) {
  const d = Store.get(), code = String(Math.floor(100000 + Math.random() * 900000));
  const ttl = bug("B02") ? 15 * MIN : 10 * MIN;                               // B02: OTP valid 15 min, not 10
  d.otps.push({ subject, code, expires: now().getTime() + ttl, used: false });
  Store.save();
  notify("SMS", mobile, `KVTU: Your OTP is ${code}. Valid for 10 minutes. Do not share it.`);
  if (email) notify("Email", email, `Your KVTU sign-in OTP is ${code}. It is valid for 10 minutes.`);
}
function checkOtp(subject, code) {
  const d = Store.get();
  const o = [...d.otps].reverse().find(x => x.subject === subject && x.code === code);
  if (!o) return t("Incorrect OTP.");
  if (o.used && !bug("B03")) return t("This OTP has already been used. Request a new one.");    // B03: OTP reusable
  if (now().getTime() > o.expires) return t("This OTP has expired. Request a new one.");
  o.used = true; Store.save();
  return null;
}

route("#/otp", {
  render: () => `
  <section class="card narrow">
    <h1>${t("Enter OTP")}</h1>
    <p class="muted">${t("We sent a 6-digit OTP to your mobile and e-mail. It is valid for 10 minutes.")}
      <a href="#/qa?tab=outbox">${t("(Practice system: read it in the QA panel inbox)")}</a></p>
    <form id="f-otp">
      ${bug("B54") ? `<input id="otp" placeholder="______" inputmode="numeric" maxlength="6" class="otp">`      // B54: no label, low contrast hint
                   : field("otp", "One-Time Password (OTP)", `<input id="otp" inputmode="numeric" maxlength="6" class="otp" autocomplete="one-time-code">`)}
      <p class="${bug("B54") ? "hint-low" : "muted"}">${t("Didn't get it? Go back and request a new OTP.")}</p>
      <button class="btn primary" type="submit">${t("Verify and sign in")}</button>
    </form>
  </section>`,
  after: () => on("f-otp", "submit", e => {
    e.preventDefault();
    const usn = sessionStorage.getItem("pendingUsn");
    if (!usn) { flash("error", t("Start again from the sign-in page.")); return go("#/login"); }
    const err = checkOtp("student:" + usn, val("otp"));
    if (err) { flash("error", err); return render(); }
    Store.get().session = { kind: "student", usn }; Store.save();
    flash("ok", t("Signed in. Your profile has been loaded from University records."));
    go("#/student");
  }),
});

/* ---- staff sign-in with 2FA: NFR-03 --------------------------------------------- */
route("#/staff/login", {
  render: () => `
  <section class="card narrow">
    <h1>${t("Staff sign in")}</h1>
    <form id="f-staff">
      ${field("user", "Username", `<input id="user" autocomplete="username">`)}
      ${field("pass", "Password", `<input id="pass" type="password" autocomplete="current-password">`)}
      <div class="field check"><input id="remember" type="checkbox"><label for="remember">${t("Remember this device")}</label></div>
      <button class="btn primary" type="submit">${t("Continue")}</button>
    </form>
    <p class="muted small">${t("Practice accounts are listed in the QA panel.")}</p>
  </section>`,
  after: () => on("f-staff", "submit", e => {
    e.preventDefault();
    const u = staffUser(val("user").toLowerCase());
    if (!u || val("pass") !== Store.get().staffPassword) { flash("error", t("Wrong username or password.")); return render(); }
    if (bug("B57") && $("remember").checked) {                                // B57: "remember me" skips two-factor sign-in
      Store.get().session = { kind: "staff", user: u.user }; Store.save();
      return go(homeFor(u.role));
    }
    issueOtp("staff:" + u.user, "98" + String(u.user.length).padStart(8, "0"), "");
    sessionStorage.setItem("pendingStaff", u.user);
    go("#/staff/otp");
  }),
});

route("#/staff/otp", {
  render: () => `
  <section class="card narrow">
    <h1>${t("Two-factor verification")}</h1>
    <p class="muted">${t("Enter the OTP sent to your registered mobile.")} <a href="#/qa?tab=outbox">${t("(QA panel inbox)")}</a></p>
    <form id="f-sotp">${field("sotp", "One-Time Password (OTP)", `<input id="sotp" inputmode="numeric" maxlength="6" class="otp">`)}
      <button class="btn primary" type="submit">${t("Verify")}</button></form>
  </section>`,
  after: () => on("f-sotp", "submit", e => {
    e.preventDefault();
    const user = sessionStorage.getItem("pendingStaff");
    const err = user ? checkOtp("staff:" + user, val("sotp")) : t("Start again from the sign-in page.");
    if (err) { flash("error", err); return render(); }
    Store.get().session = { kind: "staff", user }; Store.save();
    go(homeFor(staffUser(user).role));
  }),
});

function homeFor(role) {
  return { clerk: "#/staff/clerk", registrar: "#/staff/registrar", dispatch: "#/staff/dispatch", finance: "#/staff/finance",
           admin: "#/admin/fees" }[role] || "#/staff/grievances";
}

/* ---- student dashboard ------------------------------------------------------------ */
route("#/student", {
  auth: "student",
  render: () => {
    const s = me(), d = Store.get();
    const apps = d.apps.filter(a => a.usn === s.usn), tks = d.tickets.filter(x => x.usn === s.usn);
    return `
    <section class="card">
      <h1>${t("My dashboard")}</h1>
      <div class="profile">
        <div><span>${t("Name")}</span><b>${esc(s.name)}</b></div>
        <div><span>${t("USN")}</span><b>${esc(s.usn)}</b></div>
        <div><span>${t("College")}</span><b>${esc(d.colleges[s.college])}</b></div>
        <div><span>${t("Branch / year")}</span><b>${esc(s.branch)} · ${s.year}</b></div>
      </div>
    </section>
    <section class="card">
      <div class="row-head"><h2>${t("My document applications")}</h2><a class="btn" href="#/apply">${t("New document request")}</a></div>
      ${apps.length ? `<table class="grid"><thead><tr><th>${t("Application ID")}</th><th>${t("Documents")}</th><th>${t("Total fee")}</th><th>${t("Status")}</th><th></th></tr></thead><tbody>
        ${apps.map(a => `<tr><td>${esc(a.id)}</td><td>${a.items.map(i => `${esc(docName(i.type))} × ${i.qty}`).join("<br>")}</td>
          <td>${inr(a.lockedFee ?? feeOf(a).total)}</td><td>${statusBadge(a.status)}</td><td><a href="#/app/${esc(a.id)}">${t("Open")}</a></td></tr>`).join("")}
      </tbody></table>` : `<p class="muted">${t("No applications yet.")}</p>`}
    </section>
    <section class="card">
      <div class="row-head"><h2>${t("My grievances")}</h2><a class="btn" href="#/grievance/new">${t("Lodge grievance")}</a></div>
      ${tks.length ? `<table class="grid"><thead><tr><th>${t("Ticket ID")}</th><th>${t("Category")}</th><th>${t("Status")}</th><th>${t("With")}</th><th></th></tr></thead><tbody>
        ${tks.map(x => `<tr><td>${esc(x.id)}</td><td>${t(x.category)}</td><td>${grvStatusBadge(x)}</td><td>${t(tierName(x))}</td><td><a href="#/grievance/${esc(x.id)}">${t("Open")}</a></td></tr>`).join("")}
      </tbody></table>` : `<p class="muted">${t("No grievances lodged.")}</p>`}
    </section>`;
  },
});
