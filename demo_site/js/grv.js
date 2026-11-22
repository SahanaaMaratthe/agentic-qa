/* KVTU practice portal: Student Grievance Redressal. FR-GRV-01..05, BR-GRV-01..03. */
"use strict";

const CATEGORIES = {
  "Exam/Results": ["Result delayed", "Result withheld", "Hall ticket problem", "Exam form problem"],
  "Marks Card Correction": ["Name spelling", "Marks mismatch", "Photo or date of birth error"],
  "Revaluation": ["Revaluation result delayed", "Answer-script photocopy not received", "Revaluation fee problem"],
  "College Infra": ["Classrooms / labs", "Hostel", "Library", "Transport"],
  "Anti-Ragging": ["Ragging incident", "Harassment", "Threat or intimidation"],
};
const TIER_ROLE = { 2: "regional", 3: "ombudsperson" };
const GRV_STATUS = { OPEN: "Open", INFO_REQUESTED: "Information requested", PENDING_ACCEPTANCE: "Resolved: awaiting your confirmation", CLOSED: "Closed" };

function ticket(id) { return Store.get().tickets.find(x => x.id === id); }

/* BR-GRV-01 / FR-GRV-02: routing */
function routeOwner(category, college) {
  if (category === "Anti-Ragging") return bug("B40") ? { role: "principal", college } : { role: "statcell" };      // B40
  if (category === "College Infra") return { role: "principal", college };
  if (category === "Revaluation" && bug("B41")) return { role: "principal", college };                            // B41
  return { role: "registrar" };                                                       // Exam/Results, Marks Card Correction, Revaluation
}
function ownerRole(x) { return x.tier === 1 ? x.owner.role : TIER_ROLE[x.tier]; }
function tierName(x) {
  if (x.tier === 1) return { principal: "College Principal", registrar: "Registrar (Evaluation)", statcell: "Statutory Cell (Anti-Ragging)" }[x.owner.role];
  return x.tier === 2 ? "Regional Center" : "Ombudsperson";
}

function slaState(x) {
  if (!["OPEN", "INFO_REQUESTED"].includes(x.status)) return null;
  const left = new Date(x.slaDue) - now();
  const amber = (bug("B44") ? 24 : 48) * HOUR;                                                                    // B44
  if (left <= 0) return { cls: "red", text: t("SLA breached") };
  const dd = Math.floor(left / DAY), hh = Math.floor((left % DAY) / HOUR);
  return { cls: left < amber ? "amber" : "green", text: `${dd} ${t("days")} ${hh} ${t("hours left")}` };
}
function grvStatusBadge(x) {
  const s = slaState(x);
  return badge(t(GRV_STATUS[x.status]), x.status === "CLOSED" ? "grey" : x.status === "PENDING_ACCEPTANCE" ? "blue" : "amber") +
         (s ? " " + badge(s.text, s.cls) : "");
}

/* ---------------------------------------------------------------- intake: FR-GRV-01 */
route("#/grievance/new", {
  auth: "student",
  render: () => {
    const s = me();
    return `<section class="card"><h1>${t("Lodge a grievance")}</h1>
      <form id="f-grv" novalidate>
        <div class="two">
          ${field("g-usn", "University Seat Number (USN)", `<input id="g-usn" value="${esc(s.usn)}" readonly>`)}
          ${field("g-mobile", "Mobile number", `<input id="g-mobile" value="${esc(s.mobile)}" inputmode="numeric" maxlength="10">`)}
          ${field("g-email", "E-mail", `<input id="g-email" type="email" value="${esc(s.email)}">`)}
          ${field("g-date", "Incident date", `<input id="g-date" type="date">`)}
          ${field("g-cat", "Category", `<select id="g-cat"><option value="">${t("Select a category")}</option>${Object.keys(CATEGORIES).map(c => `<option value="${c}">${t(c)}</option>`).join("")}</select>`)}
          ${field("g-sub", "Sub-category", `<select id="g-sub"><option value="">${t("Select a category first")}</option></select>`)}
        </div>
        ${field("g-desc", "Describe your grievance", `<textarea id="g-desc" rows="6"></textarea>`, `<span id="g-count">0</span> / 2000 ${t("characters")}`)}
        ${field("g-files", "Supporting PDFs (up to 3)", `<input id="g-files" type="file" accept=".pdf" multiple>`)}
        <p class="note">${t("Anti-ragging and harassment complaints go directly to the University Statutory Cell, not to your college.")}</p>
        <button class="btn primary" type="submit">${t("Submit grievance")}</button>
      </form></section>`;
  },
  after: () => {
    const fillSub = () => { const c = $("g-cat").value;
      $("g-sub").innerHTML = c ? CATEGORIES[c].map(x => `<option value="${x}">${t(x)}</option>`).join("") : `<option value="">${t("Select a category first")}</option>`; };
    on("g-cat", "change", fillSub);
    on("g-cat", "input", fillSub);
    on("g-desc", "input", () => { $("g-count").textContent = $("g-desc").value.length; });
    on("f-grv", "submit", e => {
      e.preventDefault();
      const s = me(), d = Store.get(), desc = $("g-desc").value, files = Array.from($("g-files").files);
      const errs = [];
      if (!/^[6-9]\d{9}$/.test(val("g-mobile"))) errs.push(t("Enter a valid 10-digit mobile number."));
      if (!/^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(val("g-email"))) errs.push(t("Enter a valid e-mail."));
      if (!val("g-cat")) errs.push(t("Choose a category."));
      if (!val("g-sub")) errs.push(t("Choose a sub-category."));
      if (!val("g-date")) errs.push(t("Enter the incident date."));
      else if (!bug("B38") && new Date(val("g-date")) > now()) errs.push(t("The incident date cannot be in the future."));   // B38
      if (desc.trim().length < 20) errs.push(t("Describe the grievance in at least 20 characters."));
      if (desc.length > (bug("B36") ? 1500 : 2000)) errs.push(t("The description can be at most 2000 characters."));           // B36
      if (files.length > (bug("B37") ? 4 : 3)) errs.push(t("Attach at most 3 PDFs."));                                         // B37
      if (files.some(f => !f.name.toLowerCase().endsWith(".pdf"))) errs.push(t("Attachments must be PDF files."));
      if (files.some(f => f.size > MAX_UPLOAD)) errs.push(t("Each attachment must be 5 MB or smaller."));
      if (errs.length) { flash("error", errs.join("<br>")); const keep = snapshot(); render(); restore(keep); return; }
      const n = Store.nextSeq("grv");
      const id = `KVTU-GRV-${now().getFullYear()}-${String(n).padStart(bug("B39") ? 4 : 5, "0")}`;                          // B39
      const owner = routeOwner(val("g-cat"), s.college), start = now();
      const x = { id, usn: s.usn, college: s.college, mobile: val("g-mobile"), email: val("g-email"), category: val("g-cat"),
                  sub: val("g-sub"), incident: val("g-date"), description: desc, files: files.map(f => ({ name: f.name, size: f.size })),
                  status: "OPEN", tier: 1, owner, created: start.toISOString(), slaStart: start.toISOString(),
                  slaDue: slaDue(start, 5).toISOString(), extensions: 0, reopens: 0, thread: [] };
      d.tickets.push(x); Store.save();
      audit("GRV", id, s.usn, "-", "OPEN", `Lodged; routed to ${tierName(x)}`);
      notify("SMS", x.mobile, `KVTU: Grievance ${id} registered and sent to ${tierName(x)}. Track it on the portal.`);
      flash("ok", `${t("Grievance registered")}: <b>${esc(id)}</b>`);
      go(`#/grievance/${id}`);
    });
  },
});
function snapshot() { const k = {}; document.querySelectorAll("#main input, #main textarea, #main select").forEach(el => { if (el.id && el.type !== "file") k[el.id] = el.value; }); return k; }
function restore(k) { for (const [id, v] of Object.entries(k)) { const el = $(id); if (el) { el.value = v; el.dispatchEvent(new Event("input")); } }
  if (k["g-sub"] && $("g-sub")) $("g-sub").value = k["g-sub"]; }

/* ---------------------------------------------------------------- student view */
route("#/grievance/:id", {
  auth: "student",
  render: ({ id }) => {
    const x = ticket(id);
    if (!x || x.usn !== me().usn) return `<section class="card"><h1>${t("Grievance not found")}</h1></section>`;
    return `<section class="card"><div class="row-head"><h1>${esc(x.id)}</h1>${grvStatusBadge(x)}</div>
      <table class="kv"><tr><th>${t("Category")}</th><td>${t(x.category)} › ${t(x.sub)}</td></tr>
        <tr><th>${t("With")}</th><td>${t(tierName(x))} (${t("tier")} ${x.tier})</td></tr>
        <tr><th>${t("Lodged")}</th><td>${fmt(x.created)}</td></tr><tr><th>${t("Respond by")}</th><td>${fmt(x.slaDue)}</td></tr></table>
      <h2>${t("Your description")}</h2><p class="pre">${esc(x.description)}</p>
      ${threadHtml(x, false)}
      ${x.status === "INFO_REQUESTED" ? `${field("reply", "Your reply", `<textarea id="reply" rows="3"></textarea>`)}<button id="send" class="btn primary">${t("Send reply")}</button>` : ""}
      ${x.status === "PENDING_ACCEPTANCE" ? acceptBox(x) : ""}
    </section>`;
  },
  after: ({ id }) => {
    const x = ticket(id), s = me(); if (!x) return;
    on("send", "click", () => {
      if (!val("reply")) return;
      x.thread.push({ ts: now().toISOString(), by: s.usn, who: "student", text: val("reply") });
      audit("GRV", x.id, s.usn, x.status, "OPEN", "Student replied"); x.status = "OPEN"; Store.save(); render();
    });
    on("satisfied", "click", () => {
      const r = bug("B50") ? Number(val("rating-n")) : Number((document.querySelector("input[name=rating]:checked") || {}).value);   // B50
      if (!bug("B50") && !(r >= 1 && r <= 5)) { flash("error", t("Choose a rating from 1 to 5 stars.")); return render(); }
      x.rating = r; audit("GRV", x.id, s.usn, x.status, "CLOSED", `Student satisfied, rating ${r}`); x.status = "CLOSED"; x.closedAt = now().toISOString();
      Store.save(); flash("ok", t("Thank you. Your grievance is closed.")); render();
    });
    on("reopen", "click", () => {
      const reason = val("reopen-why");
      if (!reason) { flash("error", t("Tell us why the resolution did not solve your problem.")); return render(); }
      x.reopens++;
      x.thread.push({ ts: now().toISOString(), by: s.usn, who: "student", text: `Reopened: ${reason}` });
      if (x.reopens >= 2 && !bug("B49")) {                                                                          // B49
        x.tier = 3; audit("GRV", x.id, s.usn, "PENDING_ACCEPTANCE", "OPEN", "Second reopen: escalated directly to Ombudsperson");
      } else audit("GRV", x.id, s.usn, "PENDING_ACCEPTANCE", "OPEN", `Reopened (${x.reopens})`);
      x.status = "OPEN";
      if (!bug("B48")) { x.slaStart = now().toISOString(); x.slaDue = slaDue(now(), 5).toISOString(); }               // B48: SLA not reset
      Store.save(); flash("ok", t("Grievance reopened.")); render();
    });
  },
});

function acceptBox(x) {
  const canReopen = true;
  return `<div class="accept"><h2>${t("Was your grievance resolved?")}</h2>
    <p class="muted">${t("If you do nothing, it closes automatically on")} ${fmt(x.acceptDue)}.</p>
    ${bug("B50") ? field("rating-n", "Rating (1 to 5 stars)", `<input id="rating-n" type="number" min="1" max="5" value="5">`)
      : `<fieldset class="stars"><legend>${t("Rating")}</legend>${[1, 2, 3, 4, 5].map(n => `<label><input type="radio" name="rating" value="${n}" ${n === 5 ? "checked" : ""}> ${"★".repeat(n)}</label>`).join("")}</fieldset>`}
    <button id="satisfied" class="btn primary">${t("Yes, I am satisfied")}</button>
    ${canReopen ? `<details><summary>${t("No, reopen it")}</summary>${field("reopen-why", "Why is it not solved?", `<textarea id="reopen-why" rows="2"></textarea>`)}
      <button id="reopen" class="btn danger">${t("Reopen grievance")}</button></details>` : ""}</div>`;
}

function threadHtml(x, officer) {
  const raw = officer && bug("B59");                                                                                  // B59: stored XSS
  const items = x.thread.map((m, i) => `<li><span class="muted">${fmt(m.ts)} · ${esc(m.who === "student" ? t("Student") : m.byName || m.by)}</span>
      <div>${raw ? m.text : esc(m.text)}</div>
      ${officer && bug("B51") && m.by === (staffMe() || {}).user ? `<button class="link" data-edit="${i}">${t("Edit")}</button> <button class="link danger" data-del="${i}">${t("Delete")}</button>` : ""}</li>`).join("");   // B51
  const log = Store.get().audit.filter(a => a.entity === "GRV" && a.id === x.id)
    .map(a => `<li>${fmt(a.ts)} · ${esc(a.actor)} · ${esc(a.from)} → ${esc(a.to)} ${a.remark ? "· " + esc(a.remark) : ""}</li>`).join("");
  return `<h2>${t("Conversation")}</h2><ul class="thread">${items || `<li class="muted">${t("No messages yet.")}</li>`}</ul>
          <details><summary>${t("Audit trail")}</summary><ul class="audit">${log}</ul></details>`;
}

/* ---------------------------------------------------------------- officer inbox */
function visibleTickets(u) {
  const all = Store.get().tickets;
  if (u.role === "admin") return all;
  return all.filter(x => {
    if (x.status === "CLOSED") return false;
    if (x.tier > 1) return TIER_ROLE[x.tier] === u.role;
    if (x.owner.role !== u.role) return false;
    return u.role !== "principal" || bug("B42") || x.owner.college === u.college;                                     // B42: other colleges visible
  });
}

route("#/staff/grievances", {
  auth: ["principal", "registrar", "regional", "ombudsperson", "statcell", "admin"],
  render: () => {
    const u = staffMe(), list = visibleTickets(u);
    return `<section class="card"><h1>${t("Grievance inbox")}</h1>
      <p class="muted">${t(tierName({ tier: u.role === "regional" ? 2 : u.role === "ombudsperson" ? 3 : 1, owner: { role: u.role } }) || "")}
        ${u.college ? " · " + esc(Store.get().colleges[u.college]) : ""}</p>
      ${list.length ? `<table class="grid"><thead><tr><th>${t("Ticket ID")}</th><th>${t("College")}</th><th>${t("Category")}</th><th>${t("Status")}</th><th>${t("Respond by")}</th><th></th></tr></thead><tbody>
      ${list.map(x => `<tr><td>${esc(x.id)}</td><td>${esc(x.college)}</td><td>${t(x.category)}</td><td>${grvStatusBadge(x)}</td><td>${fmt(x.slaDue)}</td>
        <td><a href="#/staff/grievance/${esc(x.id)}">${t("Open")}</a></td></tr>`).join("")}</tbody></table>`
      : `<p class="muted">${t("No grievances in your queue.")}</p>`}</section>`;
  },
});

route("#/staff/grievance/:id", {
  auth: ["principal", "registrar", "regional", "ombudsperson", "statcell", "admin"],
  render: ({ id }) => {
    const x = ticket(id), u = staffMe();
    if (!x || !visibleTickets(u).includes(x)) return `<section class="card"><h1>${t("Not in your queue")}</h1></section>`;
    const s = student(x.usn), act = ["OPEN", "INFO_REQUESTED"].includes(x.status) && u.role !== "admin";
    const descHtml = bug("B59") ? x.description : esc(x.description);
    return `<section class="card"><div class="row-head"><h1>${esc(x.id)}</h1>${grvStatusBadge(x)}</div>
      <table class="kv"><tr><th>${t("Student")}</th><td>${esc(s.name)} · ${esc(x.usn)} · ${esc(Store.get().colleges[x.college])}</td></tr>
        <tr><th>${t("Contact")}</th><td>${esc(x.mobile)} · ${esc(x.email)}</td></tr>
        <tr><th>${t("Category")}</th><td>${t(x.category)} › ${t(x.sub)}</td></tr><tr><th>${t("Incident date")}</th><td>${fmtDate(x.incident)}</td></tr>
        <tr><th>${t("Tier")}</th><td>${x.tier} · ${t(tierName(x))}</td></tr><tr><th>${t("Respond by")}</th><td>${fmt(x.slaDue)}</td></tr>
        <tr><th>${t("Attachments")}</th><td>${x.files.map(f => esc(f.name)).join(", ") || "-"}</td></tr></table>
      <h2>${t("Description")}</h2><div class="pre">${descHtml}</div>
      ${threadHtml(x, true)}
      ${act ? `${field("o-text", "Action taken / message to student", `<textarea id="o-text" rows="3"></textarea>`)}
        <div class="actions"><button id="o-note" class="btn">${t("Post action taken")}</button>
        <button id="o-info" class="btn">${t("Request information")}</button>
        <button id="o-resolve" class="btn primary">${t("Mark resolved")}</button>
        ${x.tier === 1 && u.role === "principal" ? `<button id="o-ext" class="btn">${t("Request 3-day extension")}</button>` : ""}</div>` : ""}
    </section>`;
  },
  after: ({ id }) => {
    const x = ticket(id), u = staffMe(); if (!x) return;
    const post = (text, to) => {
      x.thread.push({ ts: now().toISOString(), by: u.user, byName: u.name, who: "officer", text });
      audit("GRV", x.id, u.user, x.status, to, text.slice(0, 120)); x.status = to; Store.save();
    };
    on("o-note", "click", () => { const tx = val("o-text"); if (!tx) return; post(tx, x.status); render(); });
    on("o-info", "click", () => {
      const tx = val("o-text"); if (!tx) { flash("error", t("Write what information you need.")); return render(); }
      post(tx, "INFO_REQUESTED"); notify("SMS", x.mobile, `KVTU: More information needed for ${x.id}. Reply on the portal.`); render();
    });
    on("o-resolve", "click", () => {
      const tx = val("o-text"); if (!tx) { flash("error", t("Describe the resolution before marking it resolved.")); return render(); }
      post(tx, "PENDING_ACCEPTANCE");
      x.resolvedAt = now().toISOString();
      x.acceptDue = addCalendarDays(now(), bug("B47") ? 3 : 7).toISOString();                                           // B47
      Store.save();
      notify("SMS", x.mobile, `KVTU: ${x.id} marked resolved. Confirm or reopen within 7 days on the portal.`);
      notify("Email", x.email, `Your grievance ${x.id} has been resolved: ${tx}. Please confirm or reopen within 7 days.`);
      flash("ok", t("Marked resolved. The student has 7 days to confirm or reopen.")); go("#/staff/grievances");
    });
    on("o-ext", "click", () => {
      const tx = val("o-text");
      if (!tx) { flash("error", t("Write the justification for the extension.")); return render(); }
      if (x.extensions >= 1 && !bug("B46")) { flash("error", t("Only one extension is allowed per grievance.")); return render(); }   // B46
      x.extensions++; x.slaDue = addWorkingDays(new Date(x.slaDue), 3).toISOString();
      post(`Extension requested (+3 working days): ${tx}`, x.status); flash("ok", t("Extension granted: 3 working days.")); render();
    });
    document.querySelectorAll("[data-edit]").forEach(b => b.addEventListener("click", () => {                       // B51
      const m = x.thread[Number(b.dataset.edit)], nt = prompt("Edit remark", m.text);
      if (nt !== null) { m.text = nt; const a = Store.get().audit.filter(l => l.entity === "GRV" && l.id === x.id && l.actor === u.user).pop(); if (a) a.remark = nt.slice(0, 120); Store.save(); render(); }
    }));
    document.querySelectorAll("[data-del]").forEach(b => b.addEventListener("click", () => {
      x.thread.splice(Number(b.dataset.del), 1);
      const d = Store.get(); const i = d.audit.map(l => l.entity === "GRV" && l.id === x.id && l.actor === u.user).lastIndexOf(true);
      if (i >= 0) d.audit.splice(i, 1); Store.save(); render();
    }));
  },
});

/* ---------------------------------------------------------------- scheduled jobs: escalation, auto-close */
function runGrievanceJob() {
  const d = Store.get(); let changed = false;
  for (const x of d.tickets) {
    if (["OPEN", "INFO_REQUESTED"].includes(x.status)) {
      let guard = 0;
      while (new Date(x.slaDue) < now() && x.tier < 3 && guard++ < 5) {
        if (x.tier === 2 && bug("B45")) break;                                                                      // B45: never reaches tier 3
        const from = tierName(x);
        x.tier++; x.slaStart = x.slaDue; x.slaDue = slaDue(new Date(x.slaDue), 5).toISOString();
        audit("GRV", x.id, "sla-scheduler", x.status, x.status, `SLA breached at ${from}: escalated to ${tierName(x)}`);
        notify("SMS", x.mobile, `KVTU: ${x.id} was not resolved in time and has been escalated to ${tierName(x)}.`);
        changed = true;
      }
    }
    if (x.status === "PENDING_ACCEPTANCE" && x.acceptDue && new Date(x.acceptDue) <= now()) {
      audit("GRV", x.id, "sla-scheduler", x.status, "CLOSED", "Auto-closed: no response from student within 7 days");
      x.status = "CLOSED"; x.closedAt = now().toISOString(); changed = true;
      notify("SMS", x.mobile, `KVTU: ${x.id} was closed automatically.`);
    }
  }
  if (changed) Store.save();
}

function runScheduler() { runGrievanceJob(); runRefundJob(); }
