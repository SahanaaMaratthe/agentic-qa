# KVTU practice portal: answer key

> **Spoiler warning.** Test the portal first, then compare. A tester who reads this before testing learns nothing about finding bugs.

59 planted bugs: 17 Critical, 20 High, 15 Medium, 7 Low. 39 are marked *subtle*: you only see them with boundary values, timing (the QA clock), a second role, or by checking data rather than the screen.

Each bug is switched off in the **reference build** (QA panel → Mode → Reference). If you are unsure whether something is a bug, reproduce it in both builds: if the reference build behaves differently, it is planted.

Requirement IDs refer to the KVTU BRD/BRS in `requirements/` (same IDs as the VTU samples).

## Scoring yourself

| Found | Rating |
|---|---|
| 50+ | Excellent: you test boundaries, roles, time and data |
| 35–49 | Good: review the subtle ones you missed |
| 20–34 | Typical first pass: mostly visible bugs |
| < 20 | Re-read the BRS and try negative and boundary tests |

## Summary by area

| Area | Bugs |
|---|---|
| Sign-in | 5 |
| Cart | 3 |
| Eligibility | 2 |
| Upload | 4 |
| Fees | 5 |
| Payment | 6 |
| Scrutiny | 4 |
| Signing | 1 |
| Verification | 2 |
| Dispatch | 1 |
| Tracking | 2 |
| Grievance intake | 4 |
| Routing | 3 |
| SLA | 4 |
| Closure | 4 |
| Audit | 1 |
| Language | 2 |
| Accessibility | 1 |
| MIS | 2 |
| Security | 3 |

## All bugs

| ID | Bug | Severity | Requirement | Subtle |
|---|---|---|---|---|
| B01 | USN with 11 characters is accepted at sign-in | High | FR-EDD-01 | yes |
| B02 | OTP stays valid for 15 minutes | Medium | FR-EDD-01 | yes |
| B03 | The same OTP can be used twice | High | FR-EDD-01, NFR-03 | yes |
| B04 | Date of birth is not checked at sign-in | Critical | BRD Step 1.1, FR-EDD-01 |  |
| B05 | Signing out does not end the session | High | NFR-03 | yes |
| B06 | More than 10 copies can be added | Medium | FR-EDD-02 |  |
| B07 | Zero copies can be added | Medium | FR-EDD-02 |  |
| B08 | Removing a cart line does not refresh the total | High | FR-EDD-04 | yes |
| B09 | PDC allowed for a student who has not cleared all exams | Critical | BR-EDD-01 |  |
| B10 | Pre-2005 USN not sent to manual verification | Medium | BR-EDD-01 | yes |
| B11 | Files up to 5.5 MB accepted (limit is 5 MB) | Medium | FR-EDD-03 | yes |
| B12 | File type not checked from its contents | High | FR-EDD-03 (MIME headers) | yes |
| B13 | Images are not virus-scanned | Critical | FR-EDD-03 (virus scan), NFR-03 | yes |
| B14 | Grade cards not required before payment | High | BR-EDD-02, FR-EDD-03 |  |
| B15 | International courier fee is ₹2,250 (should be ₹2,500) | High | FR-EDD-04 |  |
| B16 | Delivery fee charged once per document | High | FR-EDD-04, BR-EDD-03 | yes |
| B17 | Delivery fee never goes down when you change mode | High | FR-EDD-04 | yes |
| B18 | Fee not locked at checkout | High | BR-EDD-03 (locked at checkout) | yes |
| B19 | Waiver code works on any application, more than once | Critical | BR-EDD-03 (fee waiver) | yes |
| B20 | Failed payment treated as paid | Critical | FR-EDD-05 |  |
| B21 | Gateway confirmation not verified | Critical | FR-EDD-05 (HMAC), BRS state transitions | yes |
| B22 | Refund offered after verification has started | High | BR-EDD-04 |  |
| B23 | Duplicate-debit refund scheduled for T+7 (should be T+5) | Medium | BR-EDD-04 | yes |
| B24 | Receipt always shows UPI | Medium | FR-EDD-05 (e-Receipt), BO-02 | yes |
| B25 | Double-clicking Pay creates two payments | Critical | FR-EDD-05 | yes |
| B26 | Query can be raised without a remark | Medium | BRS state transitions (mandatory remark) |  |
| B27 | More than 2 resubmissions allowed | Medium | BRS state transitions (max 2 cycles) | yes |
| B28 | Clerk can approve without the eligibility check | Critical | FR-EDD-06, BRS state transitions |  |
| B29 | Query notification sent by SMS only | Low | FR-EDD-06, BRS state transitions (SMS + Email) | yes |
| B30 | Expired DSC accepted for signing | Critical | BRS state transitions (valid Class-3 DSC) |  |
| B31 | Public verification page shows DOB and mobile | High | NFR-03, BRS data model (PII masked) |  |
| B32 | Verification matches on the first 8 characters of the hash | Critical | FR-EDD-07 (SHA-256) | yes |
| B33 | 12-character AWB accepted at dispatch | Medium | BRS state transitions (13-character barcode) | yes |
| B34 | Public tracking ignores the USN | High | FR-EDD-08 | yes |
| B35 | "Verified" milestone missing from the timeline | Low | FR-EDD-08 | yes |
| B36 | Grievance description limited to 1500 characters | Medium | FR-GRV-01 | yes |
| B37 | Four attachments allowed | Low | FR-GRV-01 |  |
| B38 | Future incident date accepted | Medium | FR-GRV-01 |  |
| B39 | Ticket ID has 4 digits instead of 5 | Low | FR-GRV-01 (ticket ID format) | yes |
| B40 | Anti-ragging complaints routed to the college principal | Critical | FR-GRV-02, BR-GRV-01 |  |
| B41 | Revaluation routed to the principal | High | FR-GRV-02 (Exam/Marks → Registrar) | yes |
| B42 | Principal sees other colleges' tickets | Critical | NFR-03 (RBAC) | yes |
| B43 | SLA counts calendar days, not working days | High | BR-GRV-02, FR-GRV-03 | yes |
| B44 | Amber warning starts at 24 h left (should be 48 h) | Low | FR-GRV-03 | yes |
| B45 | No escalation from Tier 2 to Tier 3 | Critical | BO-05, BR-GRV-02 | yes |
| B46 | SLA extension can be taken twice | Medium | BR-GRV-02 | yes |
| B47 | Resolved tickets auto-close after 3 days | High | BR-GRV-03, BRD Step 2.4 | yes |
| B48 | Reopening does not restart the SLA | High | FR-GRV-04, BR-GRV-03 | yes |
| B49 | Second reopen not escalated to the Ombudsperson | High | BR-GRV-03 | yes |
| B50 | Rating accepts values outside 1–5 | Low | FR-GRV-04 |  |
| B51 | Officer can edit or delete remarks | Critical | BO-06, BRS data model (append-only) |  |
| B52 | Grievance form labels not translated | Low | FR-GRV-05, NFR-04 | yes |
| B53 | Switching language wipes typed form data | Medium | FR-GRV-05 (instant toggle) |  |
| B54 | OTP box has no label; hint text too faint | Medium | NFR-04 (WCAG 2.1 AA) | yes |
| B55 | MIS open count leaves out escalated tickets | High | FR-GRV-05 (counts match database) | yes |
| B56 | Principal's MIS shows all colleges | High | FR-GRV-05 (role-based), NFR-03 | yes |
| B57 | "Remember this device" skips staff two-factor sign-in | Critical | NFR-03 (2FA for staff) |  |
| B58 | Staff pages open to students by URL | Critical | NFR-03 (RBAC) |  |
| B59 | Script in a grievance runs in the officer's browser (XSS) | Critical | NFR-03 (OWASP Top 10) | yes |

## Details

### B01 · USN with 11 characters is accepted at sign-in

**Severity:** High · **Area:** Sign-in · **Requirement:** FR-EDD-01 · **Where:** `#/login`

- **Steps:** Enter USN 1KV21CS0011 (11 characters) with the DOB of 1KV21CS001 and request an OTP.
- **Expected (reference build):** Rejected: a USN is exactly 10 characters.
- **Actual (practice build):** An OTP is sent; the portal matches the first 10 characters.

### B02 · OTP stays valid for 15 minutes

**Severity:** Medium · **Area:** Sign-in · **Requirement:** FR-EDD-01 · **Where:** `#/otp`

- **Steps:** Request an OTP, then use the QA panel clock to move forward 12 minutes and enter it.
- **Expected (reference build):** OTP expired after 10 minutes.
- **Actual (practice build):** OTP still accepted up to 15 minutes.

### B03 · The same OTP can be used twice

**Severity:** High · **Area:** Sign-in · **Requirement:** FR-EDD-01, NFR-03 · **Where:** `#/otp`

- **Steps:** Sign in with an OTP, sign out, go back to #/otp and enter the same code again.
- **Expected (reference build):** A used OTP is rejected.
- **Actual (practice build):** The used OTP works again.

### B04 · Date of birth is not checked at sign-in

**Severity:** Critical · **Area:** Sign-in · **Requirement:** BRD Step 1.1, FR-EDD-01 · **Where:** `#/login`

- **Steps:** Enter USN 1KV21CS001 with DOB 1999-01-01.
- **Expected (reference build):** "Details do not match our records."
- **Actual (practice build):** An OTP is sent and the user can sign in.

### B05 · Signing out does not end the session

**Severity:** High · **Area:** Sign-in · **Requirement:** NFR-03 · **Where:** `Sign out (any page)`

- **Steps:** Sign in as a student, click Sign out, then open #/student.
- **Expected (reference build):** You are asked to sign in again.
- **Actual (practice build):** The dashboard opens; the session was never cleared.

### B06 · More than 10 copies can be added

**Severity:** Medium · **Area:** Cart · **Requirement:** FR-EDD-02 · **Where:** `#/apply`

- **Steps:** Add a document with Copies = 11.
- **Expected (reference build):** Rejected: 1 to 10 copies.
- **Actual (practice build):** 11 copies are added to the cart.

### B07 · Zero copies can be added

**Severity:** Medium · **Area:** Cart · **Requirement:** FR-EDD-02 · **Where:** `#/apply`

- **Steps:** Add a document with Copies = 0.
- **Expected (reference build):** Rejected: 1 to 10 copies.
- **Actual (practice build):** A line with 0 copies is added.

### B08 · Removing a cart line does not refresh the total

**Severity:** High · **Area:** Cart · **Requirement:** FR-EDD-04 · **Where:** `#/apply`

- **Steps:** Add CMC and Migration, then remove Migration. Compare the Total fee with the table.
- **Expected (reference build):** The total drops to the CMC fee only.
- **Actual (practice build):** The total still includes the removed item until the page is reloaded.

### B09 · PDC allowed for a student who has not cleared all exams

**Severity:** Critical · **Area:** Eligibility · **Requirement:** BR-EDD-01 · **Where:** `#/apply`

- **Steps:** Sign in as 1KV20EC045 (not cleared) and add a Provisional Degree Certificate.
- **Expected (reference build):** Blocked: PDC needs all exams cleared.
- **Actual (practice build):** PDC is added and can be paid for.

### B10 · Pre-2005 USN not sent to manual verification

**Severity:** Medium · **Area:** Eligibility · **Requirement:** BR-EDD-01 · **Where:** `#/apply`

- **Steps:** Sign in as 1KV04CV001 (2004 admission) and start an application.
- **Expected (reference build):** A notice says the record will be verified manually; the application is flagged.
- **Actual (practice build):** No notice, no flag; it is treated like any other student.

### B11 · Files up to 5.5 MB accepted (limit is 5 MB)

**Severity:** Medium · **Area:** Upload · **Requirement:** FR-EDD-03 · **Where:** `#/apply`

- **Steps:** Upload 5.3MB.pdf from QA panel > Test files.
- **Expected (reference build):** Rejected: over 5 MB.
- **Actual (practice build):** Accepted.

### B12 · File type not checked from its contents

**Severity:** High · **Area:** Upload · **Requirement:** FR-EDD-03 (MIME headers) · **Where:** `#/apply`

- **Steps:** Upload fake.pdf (a text file renamed to .pdf).
- **Expected (reference build):** Rejected: not a real PDF.
- **Actual (practice build):** Accepted because the name ends in .pdf.

### B13 · Images are not virus-scanned

**Severity:** Critical · **Area:** Upload · **Requirement:** FR-EDD-03 (virus scan), NFR-03 · **Where:** `#/apply`

- **Steps:** Upload eicar.png (anti-virus test file). Compare with eicar.pdf.
- **Expected (reference build):** Both are blocked by the virus scan.
- **Actual (practice build):** eicar.pdf is blocked but eicar.png is accepted.

### B14 · Grade cards not required before payment

**Severity:** High · **Area:** Upload · **Requirement:** BR-EDD-02, FR-EDD-03 · **Where:** `#/apply`

- **Steps:** Upload only a Government ID and click Proceed to Pay.
- **Expected (reference build):** Blocked: semester grade cards are required.
- **Actual (practice build):** Goes to payment.

### B15 · International courier fee is ₹2,250 (should be ₹2,500)

**Severity:** High · **Area:** Fees · **Requirement:** FR-EDD-04 · **Where:** `#/apply, #/fees`

- **Steps:** Choose International Courier and read the delivery fee.
- **Expected (reference build):** ₹2,500.
- **Actual (practice build):** ₹2,250.

### B16 · Delivery fee charged once per document

**Severity:** High · **Area:** Fees · **Requirement:** FR-EDD-04, BR-EDD-03 · **Where:** `#/apply`

- **Steps:** Add two different documents, choose Speed Post.
- **Expected (reference build):** Delivery ₹150 once per order.
- **Actual (practice build):** Delivery ₹300 (₹150 × 2 items).

### B17 · Delivery fee never goes down when you change mode

**Severity:** High · **Area:** Fees · **Requirement:** FR-EDD-04 · **Where:** `#/apply`

- **Steps:** Choose Courier, then change back to Self-Pickup.
- **Expected (reference build):** Delivery ₹0.
- **Actual (practice build):** Delivery stays at the courier price.

### B18 · Fee not locked at checkout

**Severity:** High · **Area:** Fees · **Requirement:** BR-EDD-03 (locked at checkout) · **Where:** `#/gateway/:id`

- **Steps:** Proceed to Pay, then as admin raise the CMC fee in Fee master; open the payment page again.
- **Expected (reference build):** Amount stays at the checkout price.
- **Actual (practice build):** The new fee is charged.

### B19 · Waiver code works on any application, more than once

**Severity:** Critical · **Area:** Fees · **Requirement:** BR-EDD-03 (fee waiver) · **Where:** `#/app/:id`

- **Steps:** Registrar issues a waiver for application A. Enter that code on application B.
- **Expected (reference build):** Rejected: the code belongs to another application or was already used.
- **Actual (practice build):** Application B is marked paid for free.

### B20 · Failed payment treated as paid

**Severity:** Critical · **Area:** Payment · **Requirement:** FR-EDD-05 · **Where:** `#/gateway/:id`

- **Steps:** On the gateway choose "Failure (declined by bank)" and Pay.
- **Expected (reference build):** Status stays Payment pending; the student can retry.
- **Actual (practice build):** Status moves to Under verification.

### B21 · Gateway confirmation not verified

**Severity:** Critical · **Area:** Payment · **Requirement:** FR-EDD-05 (HMAC), BRS state transitions · **Where:** `#/qa?tab=gateway`

- **Steps:** Use QA panel > Gateway to send a forged confirmation with a wrong signature and ₹1.
- **Expected (reference build):** Ignored: signature and amount do not match.
- **Actual (practice build):** The application is marked paid.

### B22 · Refund offered after verification has started

**Severity:** High · **Area:** Payment · **Requirement:** BR-EDD-04 · **Where:** `#/app/:id`

- **Steps:** Open an application in Under verification.
- **Expected (reference build):** No refund button; fees are non-refundable after scrutiny starts.
- **Actual (practice build):** A Request refund button is shown and works.

### B23 · Duplicate-debit refund scheduled for T+7 (should be T+5)

**Severity:** Medium · **Area:** Payment · **Requirement:** BR-EDD-04 · **Where:** `#/gateway/:id, #/staff/finance`

- **Steps:** Pay with "Success, but the bank debited twice"; check the refund due date in Finance.
- **Expected (reference build):** Due 5 days after payment.
- **Actual (practice build):** Due 7 days after payment.

### B24 · Receipt always shows UPI

**Severity:** Medium · **Area:** Payment · **Requirement:** FR-EDD-05 (e-Receipt), BO-02 · **Where:** `#/receipt/:id`

- **Steps:** Pay by Card, then open the receipt.
- **Expected (reference build):** Payment method: Card.
- **Actual (practice build):** Payment method: UPI.

### B25 · Double-clicking Pay creates two payments

**Severity:** Critical · **Area:** Payment · **Requirement:** FR-EDD-05 · **Where:** `#/gateway/:id`

- **Steps:** Double-click Pay.
- **Expected (reference build):** One payment.
- **Actual (practice build):** Two payments are recorded and charged.

### B26 · Query can be raised without a remark

**Severity:** Medium · **Area:** Scrutiny · **Requirement:** BRS state transitions (mandatory remark) · **Where:** `#/staff/clerk/:id`

- **Steps:** As clerk, click Raise query with the remark empty.
- **Expected (reference build):** Blocked: a remark is required.
- **Actual (practice build):** Query raised with no remark.

### B27 · More than 2 resubmissions allowed

**Severity:** Medium · **Area:** Scrutiny · **Requirement:** BRS state transitions (max 2 cycles) · **Where:** `#/app/:id`

- **Steps:** Raise a query 3 times on the same application and resubmit each time.
- **Expected (reference build):** After 2 resubmissions the option is gone.
- **Actual (practice build):** A third resubmission is allowed.

### B28 · Clerk can approve without the eligibility check

**Severity:** Critical · **Area:** Scrutiny · **Requirement:** FR-EDD-06, BRS state transitions · **Where:** `#/staff/clerk/:id`

- **Steps:** Approve a PDC application for 1KV20EC045 (not cleared).
- **Expected (reference build):** Blocked: the Tabulation Register shows exams not cleared.
- **Actual (practice build):** Approved for signing.

### B29 · Query notification sent by SMS only

**Severity:** Low · **Area:** Scrutiny · **Requirement:** FR-EDD-06, BRS state transitions (SMS + Email) · **Where:** `#/qa?tab=outbox`

- **Steps:** Raise a query and check the QA outbox.
- **Expected (reference build):** One SMS and one e-mail.
- **Actual (practice build):** SMS only.

### B30 · Expired DSC accepted for signing

**Severity:** Critical · **Area:** Signing · **Requirement:** BRS state transitions (valid Class-3 DSC) · **Where:** `#/staff/registrar`

- **Steps:** Choose DSC-C3-2025 (expired) and sign.
- **Expected (reference build):** Rejected: the certificate has expired.
- **Actual (practice build):** The document is signed and published.

### B31 · Public verification page shows DOB and mobile

**Severity:** High · **Area:** Verification · **Requirement:** NFR-03, BRS data model (PII masked) · **Where:** `#/verify`

- **Steps:** Verify any signed certificate without signing in.
- **Expected (reference build):** Name, USN, document and date only; personal details hidden.
- **Actual (practice build):** DOB and mobile number are shown to anyone.

### B32 · Verification matches on the first 8 characters of the hash

**Severity:** Critical · **Area:** Verification · **Requirement:** FR-EDD-07 (SHA-256) · **Where:** `#/verify`

- **Steps:** Take a valid hash, keep the first 8 characters and change the rest.
- **Expected (reference build):** "Not found": the full hash must match.
- **Actual (practice build):** Reported as AUTHENTIC.

### B33 · 12-character AWB accepted at dispatch

**Severity:** Medium · **Area:** Dispatch · **Requirement:** BRS state transitions (13-character barcode) · **Where:** `#/staff/dispatch`

- **Steps:** Enter EE12345678IN (12 characters) and save.
- **Expected (reference build):** Rejected: India Post numbers are 13 characters (2 letters, 9 digits, IN).
- **Actual (practice build):** Dispatched with the invalid number.

### B34 · Public tracking ignores the USN

**Severity:** High · **Area:** Tracking · **Requirement:** FR-EDD-08 · **Where:** `#/track`

- **Steps:** Track someone else's application ID with your own USN.
- **Expected (reference build):** "No application found" unless the ID and USN belong together.
- **Actual (practice build):** Their status is shown.

### B35 · "Verified" milestone missing from the timeline

**Severity:** Low · **Area:** Tracking · **Requirement:** FR-EDD-08 · **Where:** `#/app/:id, #/track`

- **Steps:** Look at the timeline of any application.
- **Expected (reference build):** Submitted → Paid → Verified → Signed → Dispatched.
- **Actual (practice build):** Verified is missing (4 steps).

### B36 · Grievance description limited to 1500 characters

**Severity:** Medium · **Area:** Grievance intake · **Requirement:** FR-GRV-01 · **Where:** `#/grievance/new`

- **Steps:** Type 1800 characters and submit.
- **Expected (reference build):** Accepted (limit is 2000).
- **Actual (practice build):** Rejected: "Maximum 1500 characters".

### B37 · Four attachments allowed

**Severity:** Low · **Area:** Grievance intake · **Requirement:** FR-GRV-01 · **Where:** `#/grievance/new`

- **Steps:** Attach 4 PDFs and submit.
- **Expected (reference build):** Rejected: up to 3 PDFs.
- **Actual (practice build):** Submitted with 4.

### B38 · Future incident date accepted

**Severity:** Medium · **Area:** Grievance intake · **Requirement:** FR-GRV-01 · **Where:** `#/grievance/new`

- **Steps:** Set the incident date to next year.
- **Expected (reference build):** Rejected: cannot be in the future.
- **Actual (practice build):** Accepted.

### B39 · Ticket ID has 4 digits instead of 5

**Severity:** Low · **Area:** Grievance intake · **Requirement:** FR-GRV-01 (ticket ID format) · **Where:** `#/grievance/:id`

- **Steps:** Lodge a grievance and read its ID.
- **Expected (reference build):** KVTU-GRV-2026-00001.
- **Actual (practice build):** KVTU-GRV-2026-0001.

### B40 · Anti-ragging complaints routed to the college principal

**Severity:** Critical · **Area:** Routing · **Requirement:** FR-GRV-02, BR-GRV-01 · **Where:** `#/staff/grievances`

- **Steps:** Lodge an Anti-Ragging grievance; see which inbox gets it.
- **Expected (reference build):** Statutory Cell (Anti-Ragging), bypassing the college.
- **Actual (practice build):** The student's college principal.

### B41 · Revaluation routed to the principal

**Severity:** High · **Area:** Routing · **Requirement:** FR-GRV-02 (Exam/Marks → Registrar) · **Where:** `#/staff/grievances`

- **Steps:** Lodge a Revaluation grievance.
- **Expected (reference build):** Registrar (Evaluation).
- **Actual (practice build):** College principal.

### B42 · Principal sees other colleges' tickets

**Severity:** Critical · **Area:** Routing · **Requirement:** NFR-03 (RBAC) · **Where:** `#/staff/grievances`

- **Steps:** Sign in as principal.mv and open the inbox.
- **Expected (reference build):** Only Malnad Valley (MV) college tickets.
- **Actual (practice build):** Tickets from every college.

### B43 · SLA counts calendar days, not working days

**Severity:** High · **Area:** SLA · **Requirement:** BR-GRV-02, FR-GRV-03 · **Where:** `#/grievance/:id`

- **Steps:** Lodge a grievance on a Friday (use the QA clock); check "Respond by".
- **Expected (reference build):** 5 working days later (skips the weekend).
- **Actual (practice build):** 5 calendar days later.

### B44 · Amber warning starts at 24 h left (should be 48 h)

**Severity:** Low · **Area:** SLA · **Requirement:** FR-GRV-03 · **Where:** `#/staff/grievances`

- **Steps:** Advance the clock so 30 hours remain; look at the SLA badge.
- **Expected (reference build):** Amber.
- **Actual (practice build):** Still green.

### B45 · No escalation from Tier 2 to Tier 3

**Severity:** Critical · **Area:** SLA · **Requirement:** BO-05, BR-GRV-02 · **Where:** `#/staff/grievances`

- **Steps:** Let a Tier-2 ticket pass its SLA (QA clock).
- **Expected (reference build):** Escalates to the Ombudsperson (Tier 3).
- **Actual (practice build):** Stays at Tier 2, breached forever.

### B46 · SLA extension can be taken twice

**Severity:** Medium · **Area:** SLA · **Requirement:** BR-GRV-02 · **Where:** `#/staff/grievance/:id`

- **Steps:** As the officer, request an extension twice.
- **Expected (reference build):** Only one extension per ticket.
- **Actual (practice build):** Second extension granted.

### B47 · Resolved tickets auto-close after 3 days

**Severity:** High · **Area:** Closure · **Requirement:** BR-GRV-03, BRD Step 2.4 · **Where:** `#/grievance/:id`

- **Steps:** Resolve a ticket and read "auto-closes on".
- **Expected (reference build):** 7 days after resolution.
- **Actual (practice build):** 3 days after resolution.

### B48 · Reopening does not restart the SLA

**Severity:** High · **Area:** Closure · **Requirement:** FR-GRV-04, BR-GRV-03 · **Where:** `#/grievance/:id`

- **Steps:** Reopen a resolved ticket; check Respond by.
- **Expected (reference build):** A fresh 5-working-day SLA.
- **Actual (practice build):** The old (nearly expired) deadline is kept.

### B49 · Second reopen not escalated to the Ombudsperson

**Severity:** High · **Area:** Closure · **Requirement:** BR-GRV-03 · **Where:** `#/grievance/:id`

- **Steps:** Reopen the same ticket a second time.
- **Expected (reference build):** Goes straight to Tier 3 (Ombudsperson).
- **Actual (practice build):** Returns to the same officer.

### B50 · Rating accepts values outside 1–5

**Severity:** Low · **Area:** Closure · **Requirement:** FR-GRV-04 · **Where:** `#/grievance/:id`

- **Steps:** In the rating box type 0 (or 9) and click Satisfied.
- **Expected (reference build):** Only 1 to 5 stars.
- **Actual (practice build):** Saved as 0 (or 9).

### B51 · Officer can edit or delete remarks

**Severity:** Critical · **Area:** Audit · **Requirement:** BO-06, BRS data model (append-only) · **Where:** `#/staff/grievance/:id`

- **Steps:** As officer, look at your earlier message in the conversation.
- **Expected (reference build):** No edit/delete: the trail is append-only.
- **Actual (practice build):** Edit and Delete links are shown and work.

### B52 · Grievance form labels not translated

**Severity:** Low · **Area:** Language · **Requirement:** FR-GRV-05, NFR-04 · **Where:** `#/grievance/new`

- **Steps:** Switch to ಕನ್ನಡ on the grievance form.
- **Expected (reference build):** Every label in Kannada.
- **Actual (practice build):** Five labels stay in English.

### B53 · Switching language wipes typed form data

**Severity:** Medium · **Area:** Language · **Requirement:** FR-GRV-05 (instant toggle) · **Where:** `#/grievance/new`

- **Steps:** Type a description, then switch language.
- **Expected (reference build):** Text is kept.
- **Actual (practice build):** Form is cleared.

### B54 · OTP box has no label; hint text too faint

**Severity:** Medium · **Area:** Accessibility · **Requirement:** NFR-04 (WCAG 2.1 AA) · **Where:** `#/otp`

- **Steps:** Inspect the OTP field with a screen reader or browser dev-tools.
- **Expected (reference build):** A visible, linked label; hint contrast ≥ 4.5:1.
- **Actual (practice build):** No label; very light grey hint.

### B55 · MIS open count leaves out escalated tickets

**Severity:** High · **Area:** MIS · **Requirement:** FR-GRV-05 (counts match database) · **Where:** `#/mis`

- **Steps:** Compare MIS "Open" with the number of open tickets across all tiers.
- **Expected (reference build):** Includes Tier 2 and Tier 3.
- **Actual (practice build):** Counts Tier 1 only.

### B56 · Principal's MIS shows all colleges

**Severity:** High · **Area:** MIS · **Requirement:** FR-GRV-05 (role-based), NFR-03 · **Where:** `#/mis`

- **Steps:** Sign in as principal.kv and open MIS.
- **Expected (reference build):** Only KV college figures.
- **Actual (practice build):** University-wide figures.

### B57 · "Remember this device" skips staff two-factor sign-in

**Severity:** Critical · **Area:** Security · **Requirement:** NFR-03 (2FA for staff) · **Where:** `#/staff/login`

- **Steps:** Tick Remember this device and sign in.
- **Expected (reference build):** OTP is still required.
- **Actual (practice build):** Signed in with the password only.

### B58 · Staff pages open to students by URL

**Severity:** Critical · **Area:** Security · **Requirement:** NFR-03 (RBAC) · **Where:** `#/staff/clerk`

- **Steps:** Signed in as a student, type #/staff/clerk in the address bar.
- **Expected (reference build):** "You do not have access to this page".
- **Actual (practice build):** The clerk workbench opens.

### B59 · Script in a grievance runs in the officer's browser (XSS)

**Severity:** Critical · **Area:** Security · **Requirement:** NFR-03 (OWASP Top 10) · **Where:** `#/staff/grievance/:id`

- **Steps:** Lodge a grievance whose description contains <img src=x onerror=alert(1)>; open it as the officer.
- **Expected (reference build):** Shown as plain text.
- **Actual (practice build):** The script runs in the officer's session.
