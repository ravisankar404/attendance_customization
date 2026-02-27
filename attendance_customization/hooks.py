from . import __version__ as app_version

app_name = "attendance_customization"
app_title = "Attendance Customization"
app_publisher = "ravi"
app_description = "Custom fields and logic for Attendance tracking"
app_email = "ravi@campx.in"
app_license = "MIT"

# Installation
# ------------
after_install = "attendance_customization.setup.install.after_install"

# Single DocTypes (Settings pages)
single_doctypes = ["Attendance Policy Settings"]

# include js in doctype views
doctype_js = {
    "Attendance": "public/js/attendance.js"
}

# Document Events
# ---------------
# Hook on document methods and events
doc_events = {
    "Leave Application": {
        "after_insert": "attendance_customization.doctype_events.leave_application.after_insert",
        "on_update":    "attendance_customization.doctype_events.leave_application.on_update",
        "on_submit":    "attendance_customization.doctype_events.leave_application.on_submit",
        "on_cancel":    "attendance_customization.doctype_events.leave_application.on_cancel",
        "on_trash":     "attendance_customization.doctype_events.leave_application.on_trash",
    }
}

# Override DocType Classes
# ------------------------
# Allow Leave Allocation for Leave Without Pay types (e.g. Loss of Pay)
override_doctype_class = {
    "Leave Allocation": "attendance_customization.doctype_events.leave_allocation.CustomLeaveAllocation",
    "Attendance Request": "attendance_customization.doctype_events.attendance_request.CustomAttendanceRequest",
}

# Scheduled Tasks
# ---------------
scheduler_events = {
    "daily": [
        "attendance_customization.attendance_customization.tasks.late_strike_processor.daily_late_strike_processor"
    ],
    "cron": {
        # Run at 2 AM daily
        "0 2 * * *": [
            "attendance_customization.attendance_customization.tasks.late_strike_processor.daily_late_strike_processor"
        ]
    }
}

# REMOVED CONFLICTING CONFIGURATIONS:
# 1. Removed 'after_migrate' - because after_install already creates custom fields
# 2. Removed 'fixtures' - because we're creating fields programmatically, not through fixtures

# Note: Choose ONE approach for custom fields:
# Option A: Create programmatically (current approach via after_install)
# Option B: Use fixtures (export/import approach)
# Don't use both!