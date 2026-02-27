import frappe


def execute():
    """Add 'Other' option to Attendance Request Reason field and ensure it is visible."""

    # Guard: skip if Attendance Request doctype is not installed (HRMS not present)
    if not frappe.db.exists("DocType", "Attendance Request"):
        return

    # Remove the hidden property setter if it exists (reason field was hidden previously)
    frappe.db.delete("Property Setter", {
        "doc_type": "Attendance Request",
        "field_name": "reason",
        "property": "hidden",
    })

    # Set options for the reason field (Select field options can't be changed via Customize Form UI)
    frappe.make_property_setter(
        {
            "doctype": "Attendance Request",
            "fieldname": "reason",
            "property": "options",
            "value": "Work From Home\nOn Duty\nOther",
            "property_type": "Text",
        },
        validate_fields_for_doctype=False,
    )

    frappe.db.commit()
    frappe.clear_cache(doctype="Attendance Request")
