from . import __version__ as app_version

app_name = "attendance_customization"
app_title = "Attendance Customization"
app_publisher = "ravi"
app_description = "Custom fields and logic for Attendance tracking"
app_email = "ravi@campx.in"
app_license = "MIT"
required_apps = ["frappe", "erpnext", "hrms"]

# Installation
after_install = "attendance_customization.setup.install.after_install"

# Single DocTypes (Settings pages)
single_doctypes = ["Attendance Policy Settings"]

# include js in doctype views
doctype_js = {
    "Attendance": "public/js/attendance.js"
}

# Document Events
doc_events = {
    "Attendance": {
        # validate: auto-correct attendance status on half-day leave dates so
        # ProcessAttendance (delete+remark workflows) always produces HD/L or
        # HD/A correctly — no scheduler required for this to work.
        # Also updates late strike count in real-time on save.
        "validate":  "attendance_customization.doctype_events.attendance.validate",
        "on_submit": "attendance_customization.doctype_events.attendance.on_submit",
    },
    "Employee Checkin": {
        # When a checkin arrives for a date that already has a submitted Half Day
        # attendance, write in_time/out_time and link the checkin so
        # mark_attendance does not overwrite the Half Day status.
        "after_insert": "attendance_customization.doctype_events.employee_checkin.after_insert",
    },
    "Leave Application": {
        # On approval: link any checkins that arrived before the attendance was
        # created (they were skipped by employee_checkin.after_insert).
        # On rejection/cancellation: unlink checkins so mark_attendance can
        # reprocess them and produce a correct Present/Absent record.
        "on_submit":              "attendance_customization.doctype_events.leave_application.on_submit",
        "on_update_after_submit": "attendance_customization.doctype_events.leave_application.on_update_after_submit",
        "on_cancel":              "attendance_customization.doctype_events.leave_application.on_cancel",
    },
    "Attendance Request": {
        # After HRMS creates/updates the Half Day attendance, link any unlinked
        # checkins and correct half_day_status based on the actual IN+OUT pair.
        # Needed because HRMS uses db_set() (bypasses validate) when an
        # attendance record already exists for the date.
        "on_submit": "attendance_customization.doctype_events.attendance_request.on_submit",
    },
}

# Override DocType Classes
override_doctype_class = {
    "Leave Allocation": "attendance_customization.doctype_events.leave_allocation.CustomLeaveAllocation",
}

# Scheduled Tasks
scheduler_events = {
    "cron": {
        # 2 AM: process late strikes for the previous day
        "0 2 * * *": [
            "attendance_customization.attendance_customization.tasks.late_strike_processor.daily_late_strike_processor"
        ],
        # 6 AM: detect half-day leave employees who also missed their working half
        # (no checkins) → changes attendance from HD/L to HD/A so payroll
        # deducts 0.5 day salary for the absent working half.
        "0 6 * * *": [
            "attendance_customization.attendance_customization.tasks.half_day_absent_checker.check_half_day_no_show"
        ],
    }
}
