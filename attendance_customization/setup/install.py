import frappe


def after_install():
    """Run after app installation."""
    print("Setting up Attendance Customization...")

    add_attendance_request_reason_options()

    # Clear cache
    frappe.clear_cache()

    print("Attendance Customization setup complete!")


def add_attendance_request_reason_options():
    """Add 'Other' option to Attendance Request Reason field and ensure it is visible."""

    # Guard: skip if Attendance Request doctype is not installed (HRMS not present)
    if not frappe.db.exists("DocType", "Attendance Request"):
        return

    # Remove the hidden property setter if it exists
    frappe.db.delete("Property Setter", {
        "doc_type": "Attendance Request",
        "field_name": "reason",
        "property": "hidden",
    })

    # Set options (validate_fields_for_doctype=False avoids Select field validation errors)
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
