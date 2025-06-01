import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_field

def execute():
    """Create custom fields for Attendance"""
    
    # First, ensure columns exist in database
    columns = frappe.db.get_table_columns("Attendance")
    
    # Add database columns if they don't exist
    if "custom_late_penalty_applied" not in columns:
        frappe.db.sql("""
            ALTER TABLE `tabAttendance` 
            ADD COLUMN `custom_late_penalty_applied` INT(1) DEFAULT 0
        """)
    
    if "custom_original_status" not in columns:
        frappe.db.sql("""
            ALTER TABLE `tabAttendance` 
            ADD COLUMN `custom_original_status` VARCHAR(140)
        """)
    
    if "custom_is_genuine_half_day" not in columns:
        frappe.db.sql("""
            ALTER TABLE `tabAttendance` 
            ADD COLUMN `custom_is_genuine_half_day` INT(1) DEFAULT 0
        """)
    
    if "custom_half_day_type" not in columns:
        frappe.db.sql("""
            ALTER TABLE `tabAttendance` 
            ADD COLUMN `custom_half_day_type` VARCHAR(140)
        """)
    
    # Basic fields without custom_ prefix
    if "late_strike_count" not in columns:
        frappe.db.sql("""
            ALTER TABLE `tabAttendance` 
            ADD COLUMN `late_strike_count` INT DEFAULT 0
        """)
    
    if "late_incident_remark" not in columns:
        frappe.db.sql("""
            ALTER TABLE `tabAttendance` 
            ADD COLUMN `late_incident_remark` TEXT
        """)
    
    if "strike_processed" not in columns:
        frappe.db.sql("""
            ALTER TABLE `tabAttendance` 
            ADD COLUMN `strike_processed` INT(1) DEFAULT 0
        """)
    
    # Now create the custom field records
    fields = [
        {
            "dt": "Attendance",
            "fieldname": "late_strike_count",
            "label": "Late Strike Count",
            "fieldtype": "Int",
            "insert_after": "late_entry",
            "read_only": 1,
            "default": 0,
             "in_list_view": 0,  # Changed
         "hidden": 1  # Added
        },
        {
            "dt": "Attendance",
            "fieldname": "late_incident_remark",
            "label": "Late Incident Remark",
            "fieldtype": "Text",
            "insert_after": "late_strike_count",
            "read_only": 1,
              "hidden": 1  # Added
        },
        {
            "dt": "Attendance",
            "fieldname": "strike_processed",
            "label": "Strike Processed",
            "fieldtype": "Check",
            "insert_after": "late_incident_remark",
            "read_only": 1,
            "default": 0
        },
        {
            "dt": "Attendance",
            "fieldname": "custom_late_penalty_applied",
            "label": "Late Penalty Applied",
            "fieldtype": "Check",
            "insert_after": "strike_processed",
            "read_only": 1
        },
        {
            "dt": "Attendance",
            "fieldname": "custom_original_status",
            "label": "Original Status",
            "fieldtype": "Select",
            "options": "\nPresent\nAbsent\nOn Leave\nHalf Day\nWork From Home",
            "insert_after": "custom_late_penalty_applied",
            "read_only": 1,
            "hidden": 1
        },
        {
            "dt": "Attendance",
            "fieldname": "custom_is_genuine_half_day",
            "label": "Is Genuine Half Day",
            "fieldtype": "Check",
            "insert_after": "custom_original_status",
            "hidden": 1
        },
        {
            "dt": "Attendance",
            "fieldname": "custom_half_day_type",
            "label": "Half Day Type",
            "fieldtype": "Select",
            "options": "\nGenuine Shortage\nLate Penalty\nPersonal Permission\nOther",
            "insert_after": "status",
            "depends_on": "eval:doc.status=='Half Day'"
        }
    ]
    
    for field in fields:
        if not frappe.db.exists("Custom Field", {"dt": field["dt"], "fieldname": field["fieldname"]}):
            create_custom_field(field["dt"], field)
            print(f"Created field: {field['fieldname']}")
    
    frappe.db.commit()
    print("All custom fields created successfully!")