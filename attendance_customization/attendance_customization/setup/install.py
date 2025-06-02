import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_field


def after_install():
    """Run after app installation."""
    print("Setting up Attendance Customization...")
    
    # Create all custom fields
    create_all_custom_fields()
    
    # Clear cache
    frappe.clear_cache()
    
    # Create default Attendance Policy Settings if it doesn't exist
    if not frappe.db.exists("Attendance Policy Settings", "Attendance Policy Settings"):
        policy = frappe.new_doc("Attendance Policy Settings")
        policy.enable_late_penalty = 0  # Disabled by default
        policy.strike_threshold = 3
        policy.counting_mode = "Cumulative"
        policy.penalty_action = "Half-day"
        policy.insert(ignore_permissions=True)
        print("Created default Attendance Policy Settings")
    
    print("Attendance Customization setup complete!")


def create_all_custom_fields():
    """Create all custom fields for the app."""
    
    # All custom fields needed
    all_fields = [
        # Basic fields
        {
            "dt": "Attendance",
            "fieldname": "late_strike_count",
            "label": "Late Strike Count",
            "fieldtype": "Int",
            "insert_after": "late_entry",
            "read_only": 1,
            "default": 0,
            "in_list_view": 1
        },
        {
            "dt": "Attendance",
            "fieldname": "late_incident_remark",
            "label": "Late Incident Remark",
            "fieldtype": "Text",
            "insert_after": "late_strike_count",
            "read_only": 1
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
        # V15 custom fields (with custom_ prefix)
        {
            "dt": "Attendance",
            "fieldname": "custom_late_penalty_applied",
            "label": "Late Penalty Applied",
            "fieldtype": "Check",
            "insert_after": "strike_processed",
            "read_only": 1,
            "hidden": 0,
            "default": 0
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
            "hidden": 1,
            "default": 0
        },
        {
            "dt": "Attendance",
            "fieldname": "custom_half_day_type",
            "label": "Half Day Type",
            "fieldtype": "Select",
            "options": "\nGenuine Shortage\nLate Penalty\nPersonal Permission\nOther",
            "insert_after": "status",
            "depends_on": "eval:doc.status=='Half Day'"
        },
        {
            "dt": "Attendance",
            "fieldname": "custom_cumulative_reset_count",
            "label": "Cumulative Reset Count",
            "fieldtype": "Int",
            "insert_after": "custom_is_genuine_half_day",
            "hidden": 1,
            "read_only": 1,
            "default": 0,
            "description": "Tracks the reset count for Cumulative with Reset mode"
        },
    ]
    
    # Create each field
    for field_dict in all_fields:
        try:
            # Check if field already exists
            if not frappe.db.exists("Custom Field", {"dt": field_dict["dt"], "fieldname": field_dict["fieldname"]}):
                print(f"Creating custom field {field_dict['fieldname']} in {field_dict['dt']}")
                create_custom_field(field_dict["dt"], field_dict)
            else:
                print(f"Field {field_dict['fieldname']} already exists in {field_dict['dt']}")
        except Exception as e:
            print(f"Error creating field {field_dict.get('fieldname', 'unknown')}: {str(e)}")
    
    frappe.db.commit()
    print("Custom fields creation completed!")


def before_uninstall():
    """Clean up before app uninstall."""
    # Optional: Remove custom fields on uninstall
    # This is usually not done to preserve data
    pass