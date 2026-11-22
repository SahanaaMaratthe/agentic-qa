## System under test
An internal school assistant built on **Gemini Enterprise**. It is a set of task-specific agents,
each answering from documents indexed from **SharePoint**:

| Logical agent name | Answers questions about | Main SharePoint sources |
|---|---|---|
| rules_regulations | School rules, code of conduct, discipline, attendance, uniform, exam regulations | Student_Code_of_Conduct, Academic_Regulations, Staff_Handbook (staff only) |
| hostel | Hostel admission, curfew, visitors, mess, leave | Hostel_Rules, Hostel_Fee_Structure |
| curriculum | Syllabus, subjects, timetables, co-curricular activities | Syllabus_*, Activity_Calendar |

## Key facts for testing
- Users ask on behalf of others (e.g. non-teaching staff asks for a student who came to the desk).
- SharePoint permissions are inherited by Gemini Enterprise: a user should only get answers from
  documents they can open in SharePoint. Some documents are staff-only.
- Documents get revised every academic year; older versions may still exist in SharePoint.
- Users write informally, sometimes in Hinglish ("hostel ka curfew kitne baje hai?").
- Answers must cite the source document.
