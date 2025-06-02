import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_field

def execute():
    """Add cumulative reset count field to Attendance"""
    
    # Check if column exists in database
    columns = frappe.db.get_table_columns("Attendance")
    
    # Add database column if it doesn't exist
    if "custom_cumulative_reset_count" not in columns:
        frappe.db.sql("""
            ALTER TABLE `tabAttendance` 
            ADD COLUMN `custom_cumulative_reset_count` INT DEFAULT 0
        """)
    
    # Create the custom field record
    if not frappe.db.exists("Custom Field", {"dt": "Attendance", "fieldname": "custom_cumulative_reset_count"}):
        create_custom_field("Attendance", {
            "dt": "Attendance",
            "fieldname": "custom_cumulative_reset_count",
            "label": "Cumulative Reset Count",
            "fieldtype": "Int",
            "insert_after": "custom_is_genuine_half_day",
            "hidden": 1,
            "read_only": 1,
            "default": 0,
            "description": "Tracks the reset count for Cumulative with Reset mode"
        })
        print("Created field: custom_cumulative_reset_count")
    
    frappe.db.commit()
    frappe.clear_cache(doctype="Attendance")