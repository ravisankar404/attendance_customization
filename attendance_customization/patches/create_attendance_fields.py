import frappe
from attendance_customization.attendance_customization.custom_fields.attendance_custom_fields import create_custom_fields

def execute():
    """Create custom fields for Attendance."""
    create_custom_fields()
