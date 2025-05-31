# Hooks for Attendance DocType

import frappe
from frappe.utils import today, getdate

def validate_attendance(doc, method):
    """Validate attendance and set late strike count."""
    if doc.late_entry:
        # Just log for debugging, don't process penalty here
        frappe.log_error(
            f"Late entry marked for {doc.employee} on {doc.attendance_date}",
            "Late Entry Validation"
        )
    
    # Set late strike count to 0 for new records
    if hasattr(doc, 'late_strike_count') and doc.is_new():
        doc.late_strike_count = 0


def after_submit_attendance(doc, method):
    """After submit, check if we need to process penalties."""
    if not doc.late_entry:
        return
        
    # IMPORTANT: Don't process penalties immediately!
    # The late strike processor should run as a scheduled job
    
    # Just log for debugging
    frappe.log_error(
        f"Attendance submitted for {doc.employee} on {doc.attendance_date}. Late Entry: {doc.late_entry}",
        "Attendance Submitted"
    )
