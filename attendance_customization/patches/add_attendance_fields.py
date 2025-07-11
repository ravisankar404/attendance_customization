import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields

def execute():
    """Add custom fields to Attendance DocType"""
    
    custom_fields = {
        "Attendance": [
            {
                "fieldname": "late_strike_count",
                "label": "Late Strike Count",
                "fieldtype": "Int",
                "insert_after": "early_exit",
                "description": "Count of late arrivals within current month",
                "default": 0,
                "in_list_view": 1,
                "translatable": 0,
                 "hidden": 1 
            },
            {
                "fieldname": "late_incident_remark",
                "label": "Late Incident Remark",
                "fieldtype": "Small Text",
                "insert_after": "late_strike_count",
                "translatable": 0
            },
            {
                "fieldname": "strike_processed",
                "label": "Strike Processed",
                "fieldtype": "Check",
                "insert_after": "late_incident_remark",
                "description": "Flag to indicate if this attendance entry has been evaluated by the scheduler",
                "default": 0,
                "translatable": 0
            }
        ]
    }
    
    create_custom_fields(custom_fields)
    frappe.db.commit()
