# Custom fields for Attendance DocType

def get_custom_fields():
    """Get all custom fields for Attendance."""
    return {
        "Attendance": [
            {
                "fieldname": "late_strike_count",
                "label": "Late Strike Count",
                "fieldtype": "Int",
                "insert_after": "late_entry",
                "read_only": 1,
                "in_list_view": 0,  # Changed from 1 to 0
                "hidden": 1,  # Added this to hide
                "description": "Count of late arrivals within current month",
                "translatable": 0
            },
            {
                "fieldname": "late_incident_remark",
                "label": "Late Incident Remark",
                "fieldtype": "Text",
                "insert_after": "late_strike_count",
                "read_only": 1,
                "translatable": 0
            },
            {
                "fieldname": "strike_processed",
                "label": "Strike Processed",
                "fieldtype": "Check",
                "insert_after": "late_incident_remark",
                "read_only": 1,
                  "hidden": 1,
                "description": "Flag to indicate if this attendance entry has been evaluated by the scheduler",
                "translatable": 0
            },
            {
                "fieldname": "custom_late_penalty_applied",
                "label": "Late Penalty Applied",
                "fieldtype": "Check",
                "insert_after": "strike_processed",
                "read_only": 1,
                "hidden": 0,
                "description": "Indicates if late penalty has been applied",
                "translatable": 0
            },
            {
                "fieldname": "custom_half_day_type",
                "label": "Half Day Type",
                "fieldtype": "Select",
                "options": "\nGenuine Shortage\nLate Penalty\nPersonal Permission\nOther",
                "insert_after": "status",
                "depends_on": "eval:doc.status=='Half Day'",
                "description": "Reason for half day status"
             },
             {
                 "fieldname": "custom_is_genuine_half_day",
                 "label": "Is Genuine Half Day",
                 "fieldtype": "Check",
                 "insert_after": "custom_half_day_type",
                 "hidden": 1,
                 "description": "Flag to indicate if half-day is genuine (not penalty)"
             },
             {
                 "fieldname": "custom_original_status",
                 "label": "Original Status",
                 "fieldtype": "Select",
                 "options": "\nPresent\nAbsent\nOn Leave\nHalf Day\nWork From Home",
                 "insert_after": "custom_late_penalty_applied",
                 "read_only": 1,
                 "hidden": 1,
                 "description": "Original attendance status before penalty",
                 "translatable": 0
             },
             
             {
                 "fieldname": "custom_cumulative_reset_count",
                 "label": "Cumulative Reset Count",
                 "fieldtype": "Int",
                 "insert_after": "custom_is_genuine_half_day",
                 "hidden": 1,
                 "read_only": 1,
                 "default": 0,
                 "description": "Tracks the reset count for Cumulative with Reset mode",
                 "translatable": 0
             }
                ]
    }
 
 
def create_custom_fields():
    """Create all custom fields for the app."""
    import frappe
    from frappe.custom.doctype.custom_field.custom_field import create_custom_field
    
    custom_fields = get_custom_fields()
    
    for doctype, fields in custom_fields.items():
        for field_dict in fields:
            # Check if field already exists
            if not frappe.db.exists("Custom Field", {"dt": doctype, "fieldname": field_dict["fieldname"]}):
                print(f"Creating custom field {field_dict['fieldname']} in {doctype}")
                create_custom_field(doctype, field_dict)
            else:
                print(f"Field {field_dict['fieldname']} already exists in {doctype}")
    
    frappe.db.commit()
    print("Custom fields creation completed!")