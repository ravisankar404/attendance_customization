import frappe


def execute():
    """Add 'Other' option to Attendance Request Reason field."""
    frappe.make_property_setter({
        "doctype": "Attendance Request",
        "fieldname": "reason",
        "property": "options",
        "value": "Work From Home\nOn Duty\nOther",
        "property_type": "Text",
    })
    frappe.clear_cache()
