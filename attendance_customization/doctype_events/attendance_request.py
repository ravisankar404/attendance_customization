import frappe
from frappe import _
from frappe.utils import format_date, get_link_to_form, getdate

from hrms.hr.doctype.attendance_request.attendance_request import AttendanceRequest


class CustomAttendanceRequest(AttendanceRequest):
    """
    Extends AttendanceRequest to allow proper half-day attendance marking
    even when the employee has an approved half-day leave on that date.

    The standard logic blocks attendance creation for any date with an
    approved leave record. But for a half-day leave, we intentionally want
    to mark the attendance as "Half Day" — the Attendance Request is created
    from the leave itself, so the block is counterproductive.

    Helper methods (get_attendance_record, get_attendance_status) are defined
    directly here so the class is self-contained across different HRMS versions
    — those methods were extracted as standalone helpers only in a later HRMS
    patch, so relying on them via inheritance can cause AttributeError on
    deployments that have an older build.
    """

    def get_attendance_record(self, attendance_date: str):
        """
        Return the name of the existing non-cancelled Attendance record for
        this employee on the given date, or None if no such record exists.
        Cancelled records (docstatus=2) are intentionally excluded so they
        do not block a fresh attendance from being created.
        """
        return frappe.db.exists(
            "Attendance",
            {
                "employee": self.employee,
                "attendance_date": attendance_date,
                "docstatus": ("!=", 2),
            },
        )

    def get_attendance_status(self, attendance_date: str) -> str:
        """
        Determine the correct Attendance status for the given date:
        - "Half Day"      if this is the half_day_date of the request
        - "Work From Home" if the reason is Work From Home
        - "Present"       for all other cases (including manual full-day requests)
        """
        if (
            self.half_day
            and self.half_day_date
            and getdate(self.half_day_date) == getdate(attendance_date)
        ):
            return "Half Day"
        if self.reason == "Work From Home":
            return "Work From Home"
        return "Present"

    def should_mark_attendance(self, attendance_date: str) -> bool:
        """
        For the specific half-day date, skip the leave-record check.
        For all other dates (multi-day requests), use standard logic.
        """
        from erpnext.setup.doctype.employee.employee import is_holiday

        # Holiday check applies always
        if not self.include_holidays and is_holiday(self.employee, attendance_date):
            frappe.msgprint(
                _("Attendance not submitted for {0} as it is a Holiday.").format(
                    frappe.bold(format_date(attendance_date))
                )
            )
            return False

        # For the half-day date: bypass the leave-record block so the
        # attendance is correctly set to "Half Day".
        # Guard against half_day_date being None (corrupted data / bypass scenario).
        if self.half_day and self.half_day_date and getdate(self.half_day_date) == getdate(attendance_date):
            return True

        # For non-half-day dates: use standard logic (includes leave check)
        return super().should_mark_attendance(attendance_date)

    def create_or_update_attendance(self, date: str):
        """
        Override to always link the attendance record to this Attendance Request,
        even when the existing attendance already has the correct status
        (which happens when Leave Application's update_attendance() ran first).

        Edge cases handled:
        - Existing attendance with correct status  → just link the request name.
        - Existing attendance with wrong status    → update status + link + comment.
        - No existing attendance                  → create and submit a new record.
        """
        attendance_name = self.get_attendance_record(date)
        status = self.get_attendance_status(date)

        if attendance_name:
            doc = frappe.get_doc("Attendance", attendance_name)
            old_status = doc.status

            if old_status != status:
                # Status needs updating — update both status and request link
                doc.db_set({"status": status, "attendance_request": self.name})
                text = _("Changed status from {0} to {1} via Attendance Request").format(
                    frappe.bold(old_status), frappe.bold(status)
                )
                doc.add_comment(comment_type="Info", text=text)
                frappe.msgprint(
                    _("Updated status from {0} to {1} for {2} in {3}").format(
                        frappe.bold(old_status),
                        frappe.bold(status),
                        frappe.bold(format_date(date)),
                        get_link_to_form("Attendance", doc.name),
                    ),
                    title=_("Attendance Updated"),
                )
            else:
                # Status is already correct — just link to this request
                doc.db_set("attendance_request", self.name)
        else:
            # No existing record — create a new submitted attendance
            doc = frappe.new_doc("Attendance")
            doc.employee = self.employee
            doc.employee_name = frappe.db.get_value("Employee", self.employee, "employee_name")
            doc.attendance_date = date
            doc.company = self.company
            doc.attendance_request = self.name
            doc.status = status
            doc.insert(ignore_permissions=True)
            doc.submit()
