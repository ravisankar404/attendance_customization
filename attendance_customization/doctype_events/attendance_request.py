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

    # ──────────────────────────────────────────────────────────────────────────
    # Read helpers
    # ──────────────────────────────────────────────────────────────────────────

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
        - "Half Day"       if this is the half_day_date of the request
        - "Work From Home" if the reason is Work From Home
        - "Present"        for all other cases (including manual full-day requests)
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

    # ──────────────────────────────────────────────────────────────────────────
    # Validation overrides
    # ──────────────────────────────────────────────────────────────────────────

    def validate_no_attendance_to_create(self):
        """
        Cloud HRMS added this method to validate() — it throws if every day in
        the request range shows as "Skip" in get_attendance_warnings(). For
        half-day ARs auto-created from a half-day leave, the approved leave is
        EXPECTED to be there, so has_leave_record() always returns True for the
        date and all warnings get action="Skip". This would incorrectly block
        submission. We bypass the check for half-day requests; our overrides of
        should_mark_attendance() and create_or_update_attendance() already handle
        the half-day leave scenario correctly. For non-half-day requests we call
        the parent if it exists (older HRMS versions don't have this method).
        """
        if self.half_day and self.half_day_date:
            # Half-day AR: the leave exists by design — skip this validation.
            return

        # Non-half-day AR: delegate to parent if present (cloud HRMS only).
        parent_validate = getattr(super(), "validate_no_attendance_to_create", None)
        if parent_validate:
            parent_validate()

    def should_mark_attendance(self, attendance_date: str) -> bool:
        """
        For the specific half-day date, skip the leave-record check.
        For all other dates (multi-day requests), use standard logic.

        Holiday check is always applied first — we never mark attendance
        on a holiday even if it is the half_day_date.
        """
        try:
            from erpnext.setup.doctype.employee.employee import is_holiday
            if not self.include_holidays and is_holiday(self.employee, attendance_date):
                frappe.msgprint(
                    _("Attendance not submitted for {0} as it is a Holiday.").format(
                        frappe.bold(format_date(attendance_date))
                    )
                )
                return False
        except ImportError:
            # erpnext path changed in a future version — fall back to parent for holiday check.
            pass

        # For the half-day date: bypass the leave-record block so the
        # attendance is correctly set to "Half Day".
        # Guard against half_day_date being None (corrupted data / bypass scenario).
        if (
            self.half_day
            and self.half_day_date
            and getdate(self.half_day_date) == getdate(attendance_date)
        ):
            return True

        # For non-half-day dates: use standard logic (includes leave check).
        return super().should_mark_attendance(attendance_date)

    # ──────────────────────────────────────────────────────────────────────────
    # Attendance write / lifecycle
    # ──────────────────────────────────────────────────────────────────────────

    def create_or_update_attendance(self, date: str):
        """
        Override to always link the attendance record to this Attendance Request,
        even when the existing attendance already has the correct status
        (which happens when Leave Application's update_attendance() ran first).

        Edge cases handled:
        1. Existing submitted attendance, correct status  → link the request name only.
        2. Existing submitted attendance, wrong status    → update status + link + comment.
        3. Existing DRAFT attendance                      → link, fix status if needed,
                                                            then submit it so payroll picks it up.
        4. No existing attendance                         → create + submit a new record.
           - If submit fails, the orphan draft is deleted and the error is logged.
        5. employee_name null-safe: falls back to self.employee_name if DB lookup returns None.
        """
        attendance_name = self.get_attendance_record(date)
        status = self.get_attendance_status(date)

        if attendance_name:
            self._link_existing_attendance(attendance_name, status, date)
        else:
            self._create_and_submit_attendance(date, status)

    def _link_existing_attendance(self, attendance_name: str, status: str, date: str):
        """
        Link this AR to an existing attendance record.
        Handles both submitted and draft states, and corrects wrong status if needed.
        """
        doc = frappe.get_doc("Attendance", attendance_name)
        old_status = doc.status
        status_changed = old_status != status

        # Write the correct status and link together in a single db_set call
        # to avoid a window where status is wrong but AR link is set (or vice-versa).
        update_fields = {"attendance_request": self.name}
        if status_changed:
            update_fields["status"] = status

        doc.db_set(update_fields)

        if status_changed:
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

        # Edge case: pre-existing record is a draft (e.g. Leave Application
        # insert succeeded but submit failed). Submit it now so payroll can
        # process it. Without this, a draft attendance is silently ignored.
        if doc.docstatus == 0:
            self._submit_draft_attendance(doc)

    def _submit_draft_attendance(self, doc):
        """
        Submit a draft attendance record that was linked but never submitted.
        Safe to call on any draft — errors are logged without crashing the AR.
        """
        try:
            doc.reload()  # Reload after db_set so submit sees the latest field values.
            doc.flags.ignore_permissions = True
            doc.submit()
        except Exception:
            frappe.log_error(
                message=frappe.get_traceback(),
                title="Failed to submit pre-existing draft Attendance {0} via AR {1}".format(
                    doc.name, self.name
                ),
            )
            frappe.msgprint(
                _("Attendance record {0} exists as a draft but could not be submitted. "
                  "Please submit it manually or check the Error Log.").format(
                    frappe.bold(doc.name)
                ),
                indicator="orange",
                title=_("Draft Attendance Not Submitted"),
            )

    def _create_and_submit_attendance(self, date: str, status: str):
        """
        Create a brand-new Attendance record and immediately submit it.

        If submit fails after insert, the orphan draft is deleted so no ghost
        records remain in the database. The error is logged and surfaced as a
        soft warning so the admin can investigate.
        """
        doc = frappe.new_doc("Attendance")
        doc.employee = self.employee
        # Null-safe: fall back to self.employee_name if DB lookup returns None
        # (e.g. employee record deleted after AR was created).
        doc.employee_name = (
            frappe.db.get_value("Employee", self.employee, "employee_name")
            or getattr(self, "employee_name", None)
            or ""
        )
        doc.attendance_date = date
        doc.company = self.company
        doc.attendance_request = self.name
        doc.status = status
        doc.flags.ignore_permissions = True

        try:
            doc.insert()
        except Exception:
            frappe.log_error(
                message=frappe.get_traceback(),
                title="Failed to insert Attendance from AR {0} for {1}".format(self.name, date),
            )
            frappe.msgprint(
                _("Could not create Attendance record for {0}. "
                  "Please check the Error Log.").format(frappe.bold(format_date(date))),
                indicator="orange",
                title=_("Attendance Creation Failed"),
            )
            return

        try:
            doc.submit()
        except Exception:
            # submit failed — clean up the orphan draft so it does not linger.
            frappe.log_error(
                message=frappe.get_traceback(),
                title="Failed to submit Attendance {0} from AR {1}".format(doc.name, self.name),
            )
            try:
                frappe.delete_doc("Attendance", doc.name, ignore_permissions=True)
            except Exception:
                pass  # Best-effort cleanup; original error is already logged.

            frappe.msgprint(
                _("Could not submit Attendance record for {0}. "
                  "Please check the Error Log.").format(frappe.bold(format_date(date))),
                indicator="orange",
                title=_("Attendance Submission Failed"),
            )

    # ──────────────────────────────────────────────────────────────────────────
    # Cancel lifecycle
    # ──────────────────────────────────────────────────────────────────────────

    def on_cancel(self):
        """
        Extends the parent on_cancel to also clean up DRAFT attendance records
        linked to this AR.

        The parent only cancels submitted (docstatus=1) attendance. But if
        submit ever failed after insert in create_or_update_attendance (and the
        cleanup there also failed), a ghost draft attendance with
        attendance_request=self.name could remain. This handles that case.
        """
        # Parent handles submitted (docstatus=1) records via attendance_obj.cancel()
        super().on_cancel()

        # Also delete any lingering draft attendance records linked to this AR.
        draft_attendances = frappe.get_all(
            "Attendance",
            filters={
                "employee": self.employee,
                "attendance_request": self.name,
                "docstatus": 0,
            },
            fields=["name"],
        )
        for record in draft_attendances:
            try:
                frappe.delete_doc("Attendance", record.name, ignore_permissions=True)
            except Exception:
                frappe.log_error(
                    message=frappe.get_traceback(),
                    title="Failed to delete draft Attendance {0} on AR cancel {1}".format(
                        record.name, self.name
                    ),
                )
