# Project Memory

## App Info
- App: attendance_customization
- **Site: fresh.local** (NOT campx.dev — campx.dev does not have this app)
- Framework: Frappe v14 / ERPNext v14 / HRMS v14
- URL: campx.localhost:8000 maps to fresh.local

## Key Files
- `attendance_customization/hooks.py` — doc_events + override_doctype_class
- `attendance_customization/doctype_events/leave_application.py` — Half-day leave → Attendance Request automation
- `attendance_customization/doctype_events/attendance_request.py` — CustomAttendanceRequest override
- `attendance_customization/doctype_events/leave_allocation.py` — CustomLeaveAllocation (allows LOP allocation)
- `attendance_customization/doctype_events/attendance.py` — Late strike count logic

## Half-Day Leave → Attendance Request Feature
**Triggers**: 4 hooks on Leave Application
  - after_insert → create DRAFT Attendance Request (fires when employee first saves/applies)
  - on_submit    → submit the draft AR (fires when leave is approved+submitted)
  - on_cancel    → cancel submitted AR + delete draft AR
  - on_trash     → delete draft AR when draft leave is deleted

**Key**: Users "apply" by SAVING (docstatus=0, status=Open). on_submit alone was wrong
because users never went through the approve+submit flow.

**Override**: CustomAttendanceRequest overrides `should_mark_attendance` to bypass the
  `has_leave_record` block for half-day dates — so attendance gets properly linked.
  Also overrides `create_or_update_attendance` to always link existing attendance.

### Key Bugs Fixed
- `reason="Half Day Leave"` was invalid — Attendance Request reason is a Select field with options: "Work From Home", "On Duty", "Other"
- No `status == "Approved"` check — rejected leaves would have triggered creation
- `has_leave_record` in standard AttendanceRequest blocks attendance for approved leaves → overridden in CustomAttendanceRequest
- Leave Application's `update_attendance()` already creates attendance before our hook fires (hook fires after ERPNext's own on_submit)

## Attendance Request reason field options
`Work From Home`, `On Duty`, `Other` (Other added by patch: add_attendance_request_other_reason)

## Important ERPNext/HRMS Behaviours
- Leave Application can only be submitted when status = "Approved" or "Rejected"
- Leave Application.update_attendance() creates Attendance records (status=Half Day or On Leave)
- Attendance.check_leave_record() auto-sets status to Half Day/On Leave based on approved leave
- bench --site campx.dev clear-cache  ← required after hooks.py changes
