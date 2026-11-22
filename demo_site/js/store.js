/* KVTU practice portal: data store, mock clock, notifications, audit trail, helpers.
   Everything lives in the browser's localStorage, so the site needs no server. */
"use strict";

const KEY = "kvtu_practice_v1";
const DAY = 86400000, HOUR = 3600000, MIN = 60000;

const SEED = () => ({
  mode: "buggy",                 // "buggy" | "correct"  (QA panel switch)
  lang: "en",
  clockOffset: 0,                // ms added to the real time (QA panel moves the clock)
  session: null,                 // {kind:"student", usn} | {kind:"staff", user}
  seq: { app: 1, grv: 1, pay: 1, log: 1, dispatch: 1 },
  students: [
    { usn: "1KV21CS001", name: "Ananya Rao", dob: "2003-04-12", email: "ananya.rao@example.edu", mobile: "9845012345",
      college: "KV", branch: "CS", year: 2021, cleared: true, nad: "NAD-ABC-30021" },
    { usn: "1KV20EC045", name: "Rahul Shetty", dob: "2002-09-30", email: "rahul.shetty@example.edu", mobile: "9900112233",
      college: "KV", branch: "EC", year: 2020, cleared: false, nad: "NAD-ABC-30022" },
    { usn: "2MV19ME010", name: "Fatima Khan", dob: "2001-01-05", email: "fatima.khan@example.edu", mobile: "9731122334",
      college: "MV", branch: "ME", year: 2019, cleared: true, nad: "NAD-ABC-30023" },
    { usn: "1KV04CV001", name: "Suresh Gowda", dob: "1985-07-21", email: "suresh.gowda@example.com", mobile: "9448800001",
      college: "KV", branch: "CV", year: 2004, cleared: true, legacy: true, nad: "" },
    { usn: "3PE22AI007", name: "Meera Iyer", dob: "2004-11-18", email: "meera.iyer@example.edu", mobile: "9611223344",
      college: "PE", branch: "AI", year: 2022, cleared: false, nad: "NAD-ABC-30025" },
  ],
  // Tabulation Register (what the exam clerk compares uploads against)
  tr: {
    "1KV21CS001": { sgpa: [8.1, 8.4, 7.9, 8.8, 8.2, 8.6, 8.9, 9.0], result: "PASS - First Class with Distinction" },
    "1KV20EC045": { sgpa: [6.2, 5.8, 0, 6.0, 0, 6.4], result: "BACKLOG - 2 subjects pending" },
    "2MV19ME010": { sgpa: [7.1, 7.4, 7.0, 7.6, 7.2, 7.9, 8.0, 8.1], result: "PASS - First Class" },
    "1KV04CV001": { sgpa: [], result: "LEGACY RECORD - manual verification" },
    "3PE22AI007": { sgpa: [8.8, 9.1, 8.7, 9.2], result: "IN PROGRESS - 4 semesters completed" },
  },
  colleges: {
    KV: "Kaveri Institute of Technology", MV: "Malnad Valley College of Engineering", PE: "Pennar Engineering College",
  },
  staff: [
    { user: "clerk", name: "S. Prakash", role: "clerk" },
    { user: "registrar", name: "Dr. R. Menon", role: "registrar" },
    { user: "dispatch", name: "K. Joseph", role: "dispatch" },
    { user: "principal.kv", name: "Dr. A. Kulkarni", role: "principal", college: "KV" },
    { user: "principal.mv", name: "Dr. N. Hegde", role: "principal", college: "MV" },
    { user: "principal.pe", name: "Dr. V. Reddy", role: "principal", college: "PE" },
    { user: "regional", name: "Regional Director", role: "regional" },
    { user: "ombuds", name: "Justice (Retd.) L. Pai", role: "ombudsperson" },
    { user: "statcell", name: "Statutory Cell Nodal Officer", role: "statcell" },
    { user: "finance", name: "Finance Officer", role: "finance" },
    { user: "admin", name: "ICT Administrator", role: "admin" },
  ],
  staffPassword: "Demo@123",
  fees: { PDC: 1000, CMC: 500, TRANSCRIPT: 750, MIGRATION: 600 },
  delivery: { SELF: 0, SPEED: 150, COURIER: 2500 },
  apps: [], payments: [], refunds: [], waivers: [],
  tickets: [],
  audit: [], outbox: [], otps: [], dsc: [
    { id: "DSC-C3-2027", label: "Class-3 DSC, Dr. R. Menon (valid until 31-Mar-2027)", cls: 3, validUntil: "2027-03-31" },
    { id: "DSC-C3-2025", label: "Class-3 DSC, Dr. R. Menon (expired 15-Jun-2025)", cls: 3, validUntil: "2025-06-15" },
    { id: "DSC-C2-2027", label: "Class-2 DSC, Office account (valid until 2027)", cls: 2, validUntil: "2027-12-31" },
  ],
});

const Store = {
  _d: null,
  get() {
    if (!this._d) {
      try { this._d = JSON.parse(localStorage.getItem(KEY)) || SEED(); } catch (e) { this._d = SEED(); }
    }
    return this._d;
  },
  save() { try { localStorage.setItem(KEY, JSON.stringify(this._d)); } catch (e) { /* storage full / private mode */ } },
  reset(keepMode) {
    const mode = this.get().mode, lang = this.get().lang;
    this._d = SEED();
    if (keepMode) { this._d.mode = mode; this._d.lang = lang; }
    this.save();
  },
  nextSeq(kind) { const d = this.get(); const n = d.seq[kind]++; this.save(); return n; },
};

/* ---- buggy / correct switch ------------------------------------------------ */
function bug(id) { return Store.get().mode === "buggy"; }      // every planted bug checks this (id = answer key)

/* ---- mock clock ------------------------------------------------------------ */
function now() { return new Date(Date.now() + (Store.get().clockOffset || 0)); }
function advanceClock(ms) { Store.get().clockOffset += ms; Store.save(); }
function isWeekend(d) { const w = d.getDay(); return w === 0 || w === 6; }
function addWorkingDays(start, n) {
  const d = new Date(start.getTime());
  let added = 0;
  while (added < n) { d.setTime(d.getTime() + DAY); if (!isWeekend(d)) added++; }
  return d;
}
function addCalendarDays(start, n) { return new Date(start.getTime() + n * DAY); }
function slaDue(start, days) {
  return bug("B43") ? addCalendarDays(start, days) : addWorkingDays(start, days);   // B43: weekends counted
}

/* ---- notifications (mock SMS / e-mail gateway) ----------------------------- */
function notify(channel, to, text) {
  Store.get().outbox.unshift({ ts: now().toISOString(), channel, to, text });
  Store.save();
}

/* ---- audit trail (append-only) --------------------------------------------- */
function audit(entity, id, actor, from, to, remark) {
  const d = Store.get();
  d.audit.push({ logId: d.seq.log++, ts: now().toISOString(), entity, id, actor, from, to, remark: remark || "" });
  Store.save();
}

/* ---- helpers --------------------------------------------------------------- */
function esc(s) {
  return String(s ?? "").replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}
function inr(n) { return "₹" + Number(n).toLocaleString("en-IN", { minimumFractionDigits: 2, maximumFractionDigits: 2 }); }
function fmt(ts) { if (!ts) return "-"; const d = new Date(ts); return d.toLocaleString("en-IN", { day: "2-digit", month: "short", year: "numeric", hour: "2-digit", minute: "2-digit" }); }
function fmtDate(ts) { if (!ts) return "-"; return new Date(ts).toLocaleDateString("en-IN", { day: "2-digit", month: "short", year: "numeric" }); }
function rand(n, chars) { chars = chars || "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"; let s = ""; for (let i = 0; i < n; i++) s += chars[Math.floor(Math.random() * chars.length)]; return s; }
function student(usn) { return Store.get().students.find(s => s.usn === usn); }
function staffUser(u) { return Store.get().staff.find(s => s.user === u); }
function maskMobile(m) { return m ? "XXXXXX" + m.slice(-4) : ""; }
function maskEmail(e) { if (!e) return ""; const [a, b] = e.split("@"); return a[0] + "***@" + b; }

/* ---- SHA-256 (pure JS, works on file:// too) -------------------------------- */
function sha256(ascii) {
  function rr(v, a) { return (v >>> a) | (v << (32 - a)); }
  const maxWord = Math.pow(2, 32); let result = ""; const words = []; const asciiBitLength = ascii.length * 8;
  let hash = [], k = []; let primeCounter = 0; const isComposite = {};
  for (let candidate = 2; primeCounter < 64; candidate++) {
    if (!isComposite[candidate]) {
      for (let i = 0; i < 313; i += candidate) isComposite[i] = candidate;
      hash[primeCounter] = (Math.pow(candidate, .5) * maxWord) | 0;
      k[primeCounter++] = (Math.pow(candidate, 1 / 3) * maxWord) | 0;
    }
  }
  hash = hash.slice(0, 8);
  ascii += "\x80"; while (ascii.length % 64 - 56) ascii += "\x00";
  for (let i = 0; i < ascii.length; i++) { const j = ascii.charCodeAt(i); if (j >> 8) return ""; words[i >> 2] |= j << ((3 - i) % 4) * 8; }
  words[words.length] = ((asciiBitLength / maxWord) | 0); words[words.length] = (asciiBitLength);
  for (let j = 0; j < words.length;) {
    const w = words.slice(j, j += 16); const oldHash = hash; hash = hash.slice(0, 8);
    for (let i = 0; i < 64; i++) {
      const w15 = w[i - 15], w2 = w[i - 2]; const a = hash[0], e = hash[4];
      const temp1 = hash[7] + (rr(e, 6) ^ rr(e, 11) ^ rr(e, 25)) + ((e & hash[5]) ^ ((~e) & hash[6])) + k[i]
        + (w[i] = (i < 16) ? w[i] : (w[i - 16] + (rr(w15, 7) ^ rr(w15, 18) ^ (w15 >>> 3)) + w[i - 7] + (rr(w2, 17) ^ rr(w2, 19) ^ (w2 >>> 10))) | 0);
      const temp2 = (rr(a, 2) ^ rr(a, 13) ^ rr(a, 22)) + ((a & hash[1]) ^ (a & hash[2]) ^ (hash[1] & hash[2]));
      hash = [(temp1 + temp2) | 0].concat(hash); hash[4] = (hash[4] + temp1) | 0;
    }
    for (let i = 0; i < 8; i++) hash[i] = (hash[i] + oldHash[i]) | 0;
  }
  for (let i = 0; i < 8; i++) for (let j = 3; j + 1; j--) { const b = (hash[i] >> (j * 8)) & 255; result += ((b < 16) ? 0 : "") + b.toString(16); }
  return result;
}

/* ---- payment gateway signature (mock HMAC) ---------------------------------- */
const GATEWAY_SECRET = "kvtu-gateway-secret";
function hmac(payload) { return sha256(GATEWAY_SECRET + "|" + payload); }
