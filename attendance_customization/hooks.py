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
    "Attendance": {
        "validate": "attendance_customization.attendance_customization.attendance_immediate_processor.on_attendance_validate",
        "on_submit": "attendance_customization.attendance_customization.attendance_immediate_processor.on_attendance_submit"
    }
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