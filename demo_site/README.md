# KVTU practice portal

A small web application to practise testing on, built from the BRD/BRS in `requirements/`.
It has **59 planted bugs** and a switch that turns all of them off.

> **Kaveri Valley Technological University (KVTU) is fictional.** The portal copies the *concepts* of the
> sample VTU requirements (eDDTS document requests and grievance redressal), not the real VTU website, its
> name or its branding. There is no real login, payment, SMS or e-mail: everything happens inside your browser.

## Start it

From the `agentic-qa` folder (virtual environment active):

```
python -m qa_agents demo-site
```

Your browser opens at http://localhost:8600/index.html. Press **Ctrl+C** in the terminal to stop.
Busy port? `python -m qa_agents demo-site --port 8601`.

You can also double-click `demo_site/index.html`. It works from the file system, but a few browsers block
file uploads there, so the command above is better.

## Two builds in one site

| Build | What it is | How to switch |
|---|---|---|
| **Practice build** (default) | All 59 bugs switched on. Test this one. | QA panel → Mode & data |
| **Reference build** | All bugs off: behaves as the BRS says. | QA panel → Mode & data |

The footer always shows which build you are on. When you are unsure whether something is a bug,
reproduce it in both builds. If the reference build behaves differently, it is a planted bug.

## Accounts

**Students** (sign in at *Student login*: USN, date of birth, any e-mail and 10-digit mobile, then the OTP):

| USN | Date of birth | Notes |
|---|---|---|
| 1KV21CS001 | 2003-04-12 | All exams cleared |
| 1KV20EC045 | 2002-09-30 | Exams **not** cleared (not eligible for PDC) |
| 2MV19ME010 | 2001-01-05 | All exams cleared, Malnad Valley college |
| 1KV04CV001 | 1985-07-21 | Pre-2005 (legacy) record |
| 3PE22AI007 | 2004-11-18 | Exams not cleared, Pennar college |

**Staff** (sign in at *Staff login*, password `Demo@123`, then the OTP):
`clerk`, `registrar`, `dispatch`, `principal.kv`, `principal.mv`, `principal.pe`, `regional`, `ombuds`,
`statcell`, `finance`, `admin`.

**OTPs, SMS and e-mails** never leave the browser. Read them in **QA panel → Outbox**.

## The QA panel (`#/qa`, link in the footer)

This is tester tooling, not part of the product, so it is **English-only and not under test**.

- **Mode & data**: switch builds, reset everything, load sample applications and tickets.
- **Clock**: move time forward (+10 minutes, +1 hour, +1 day, +1 working day and more) to test OTP expiry, SLAs, escalation and auto-close.
- **Outbox**: every SMS and e-mail the portal "sent", including OTPs.
- **Accounts**: the tables above.
- **Test files**: download ready-made files for upload testing (valid PDF, exactly 5 MB, 5.3 MB, 5.8 MB, a text file named .pdf, EICAR anti-virus test files).
- **Gateway**: send a forged payment confirmation, to test the payment webhook security.

## Answer key

`ANSWER_KEY.md` (readable) and `answer_key.json` (for tools) list every bug with steps,
expected and actual results and the requirement it breaks. **Test first, then compare.**

## Using it with the QA agents

1. Give the tool the requirements: `python -m qa_agents run --usecase demo_site/requirements/KVTU_BRD.xlsx --usecase demo_site/requirements/KVTU_BRS.xlsx`
   (or add both files on the web page). The site has no chat API, so set `target: {type: none}` in
   `config/settings.yaml` and the run stops after test design.
2. Run the generated test cases by hand against the portal and record results.
3. Compare what you found with the answer key. Any planted bug no test case could catch is a gap in the test design.

## Known differences from the BRS (by design, not bugs)

- Brand names: VTU → KVTU, ticket prefix VTU-GRV → KVTU-GRV.
- Base document fees (PDC ₹1,000, CMC ₹500, Transcript ₹750, Migration ₹600) are practice values; the BRS gives only delivery fees.
- MIS export is CSV (opens in Excel), not XLSX/PDF.
- The QR code is a drawing for practice and cannot be scanned; use the hash shown under it on the Verify page.
- Payment gateway, SMS, e-mail, virus scanner, NAD/DigiLocker and India Post are simulated.
- No performance, uptime or disaster-recovery behaviour (NFR-01, NFR-02) can be tested here.
- Data is kept in your browser's local storage. *Reset* in the QA panel starts over.

## Checking the site still works (for developers)

```
pip install playwright
playwright install chromium
python -m pytest tests/test_practice_site.py
```

This runs one automated check per bug (`demo_site/tests/checks.js`) in both builds and compares it with the
answer key. Without Playwright the browser test is skipped. To add a bug: wrap the faulty code in
`if (bug("B60")) { ... }`, add a check to `checks.js`, and add the entry to the answer key.
