import frappe
from frappe import _


# ─────────────────────────────────────────────
# Frappe document event hooks
# ─────────────────────────────────────────────

def after_insert(doc, method):
    """
    Fires once when a Leave Application is first saved (docstatus=0).
    Creates a DRAFT Attendance Request immediately so it appears as soon
    as the employee "applies" — before manager approval.

    Only runs for half-day leaves (half_day=1 and half_day_date is set).
    """
    if not _is_half_day(doc):
        return

    _create_draft_attendance_request(doc)


def on_update(doc, method):
    """
    Fires on every subsequent save of a draft Leave Application.
    Skipped on initial insert (after_insert already handled that).

    Handles the half_day field being toggled after first save:
    - half_day turned ON  (0→1): create draft AR if none exists.
    - half_day turned OFF (1→0): delete orphan draft AR.
    - half_day_date changed (1→1): replace old draft AR with new one.
    """
    # Skip on the very first insert — after_insert already handled it.
    # get_doc_before_save() returns None for newly-created documents.
    old_doc = doc.get_doc_before_save() if hasattr(doc, "get_doc_before_save") else None
    if old_doc is None:
        return

    # Only manage drafts (submitted leaves go through on_submit).
    if doc.docstatus != 0:
        return

    half_day_now = _is_half_day(doc)
    half_day_before = bool(old_doc.half_day and old_doc.half_day_date)

    if half_day_now and half_day_before:
        # Both before and after are half-day — check if the date changed.
        if str(old_doc.half_day_date) != str(doc.half_day_date):
            # half_day_date shifted: delete old draft AR and create a new one.
            old_draft = _find_attendance_request(
                old_doc.employee, old_doc.half_day_date, docstatus_filter=0
            )
            if old_draft:
                _safe_delete_ar(old_draft, "date change")
            _create_draft_attendance_request(doc)
        else:
            # Date unchanged — ensure AR exists (idempotent).
            if not _find_attendance_request(doc.employee, doc.half_day_date):
                _create_draft_attendance_request(doc)

    elif half_day_now and not half_day_before:
        # Switched from full-day to half-day — create draft AR.
        if not _find_attendance_request(doc.employee, doc.half_day_date):
            _create_draft_attendance_request(doc)

    elif not half_day_now and half_day_before:
        # Switched from half-day to full-day — delete orphan draft AR.
        old_draft = _find_attendance_request(
            old_doc.employee, old_doc.half_day_date, docstatus_filter=0
        )
        if old_draft:
            _safe_delete_ar(old_draft, "half_day disabled")


def on_submit(doc, method):
    """
    Fires when a Leave Application is submitted (docstatus 0→1).
    In HRMS, only Approved (or Rejected) leaves can be submitted.

    For Approved half-day leaves: submits the draft Attendance Request
    created in after_insert, or creates + submits one if missing.
    Rejected leaves are skipped entirely.
    """
    if not _is_half_day(doc):
        return

    if doc.status != "Approved":
        return

    _submit_attendance_request(doc)


def on_cancel(doc, method):
    """
    Fires when a Leave Application is cancelled (docstatus 1→2).
    Cancels any submitted Attendance Request and deletes any lingering drafts.

    Note: Leave Application's own cancel_attendance() already cancels the
    Attendance record (sets docstatus=2 via direct DB). AttendanceRequest.on_cancel
    looks for attendance with docstatus=1, so no double-cancellation occurs.
    """
    if not _is_half_day(doc):
        return

    _cancel_attendance_request(doc)


def on_trash(doc, method):
    """
    Fires when a draft Leave Application is deleted from the system.
    Cleans up the corresponding draft Attendance Request to avoid orphans.
    Submitted ARs are not touched here (cancel must be done before trash).
    """
    if not _is_half_day(doc):
        return

    _delete_draft_attendance_request(doc)


# ─────────────────────────────────────────────
# Internal helpers
# ─────────────────────────────────────────────

def _is_half_day(doc):
    """True only when both half_day flag and half_day_date are set."""
    return bool(doc.half_day and doc.half_day_date)


def _find_attendance_request(employee, half_day_date, docstatus_filter=None):
    """
    Return the name of the first matching Attendance Request for this
    employee + half_day_date combination, or None.

    docstatus_filter: None → any non-cancelled (docstatus != 2)
                      0    → draft only
                      1    → submitted only
    """
    filters = {
        "employee": employee,
        "from_date": half_day_date,
        "to_date": half_day_date,
        "half_day": 1,
        "half_day_date": half_day_date,
    }

    if docstatus_filter is None:
        filters["docstatus"] = ("!=", 2)
    else:
        filters["docstatus"] = docstatus_filter

    return frappe.db.get_value("Attendance Request", filters, "name")


def _has_overlapping_ar(employee, half_day_date):
    """
    Return the name of any non-cancelled Attendance Request that overlaps
    half_day_date (but is NOT an exact half-day match already caught by
    _find_attendance_request).
    """
    return frappe.db.get_value(
        "Attendance Request",
        {
            "employee": employee,
            "from_date": ("<=", half_day_date),
            "to_date": (">=", half_day_date),
            "docstatus": ("!=", 2),
        },
        "name",
    )


def _safe_delete_ar(ar_name, reason=""):
    """Silently delete a draft Attendance Request, logging any failure."""
    try:
        frappe.delete_doc("Attendance Request", ar_name, ignore_permissions=True)
    except Exception:
        frappe.log_error(
            message=frappe.get_traceback(),
            title="Failed to delete draft Attendance Request {0} ({1})".format(
                ar_name, reason
            ),
        )


def _create_draft_attendance_request(leave_doc):
    """
    Create a new DRAFT Attendance Request for the half-day date.

    Edge cases handled:
    1. Exact duplicate guard: skip if any non-cancelled AR already exists.
    2. Overlap guard: skip if another AR overlaps this date.
    3. All exceptions are caught, logged, and surfaced as a soft warning.
    """
    employee = leave_doc.employee
    half_day_date = leave_doc.half_day_date
    company = leave_doc.company

    # Guard 1: exact match already exists (draft or submitted, not cancelled)
    existing = _find_attendance_request(employee, half_day_date)
    if existing:
        frappe.msgprint(
            _("Attendance Request {0} already exists for {1} on {2}.").format(
                frappe.bold(existing),
                frappe.bold(leave_doc.employee_name),
                frappe.bold(str(half_day_date)),
            ),
            indicator="orange",
            title=_("Attendance Request Exists"),
        )
        return

    # Guard 2: overlapping Attendance Request on the same date
    overlapping = _has_overlapping_ar(employee, half_day_date)
    if overlapping:
        frappe.msgprint(
            _(
                "Could not auto-create Attendance Request for {0} on {1} — "
                "overlaps with existing request {2}."
            ).format(
                frappe.bold(leave_doc.employee_name),
                frappe.bold(str(half_day_date)),
                frappe.bold(overlapping),
            ),
            indicator="orange",
            title=_("Overlapping Attendance Request"),
        )
        return

    try:
        ar = frappe.new_doc("Attendance Request")
        ar.employee = employee
        ar.company = company
        ar.from_date = half_day_date
        ar.to_date = half_day_date
        ar.half_day = 1
        ar.half_day_date = half_day_date
        ar.reason = "On Duty"   # valid Select option on this site
        ar.explanation = _("Auto-created from Half Day Leave Application {0}").format(
            leave_doc.name
        )
        ar.flags.ignore_permissions = True
        ar.insert()             # saved as DRAFT (docstatus=0)

        frappe.msgprint(
            _("Attendance Request {0} created (Draft) for {1} on {2}.").format(
                frappe.bold(ar.name),
                frappe.bold(leave_doc.employee_name),
                frappe.bold(str(half_day_date)),
            ),
            indicator="green",
            title=_("Attendance Request Created"),
        )

    except Exception:
        frappe.log_error(
            message=frappe.get_traceback(),
            title="Auto Attendance Request (Draft) failed for Leave {0}".format(
                leave_doc.name
            ),
        )
        frappe.msgprint(
            _("Could not auto-create Attendance Request for {0} on {1}. "
              "Please check the Error Log.").format(
                frappe.bold(leave_doc.employee_name),
                frappe.bold(str(half_day_date)),
            ),
            indicator="orange",
            title=_("Auto Attendance Request Failed"),
        )


def _submit_attendance_request(leave_doc):
    """
    Called on Leave Application on_submit (status=Approved).

    Finds the draft AR and submits it. If none exists (manually deleted or
    after_insert was skipped), creates + submits directly.

    After submit, CustomAttendanceRequest.create_or_update_attendance() links
    the existing attendance record (already created by Leave Application's
    update_attendance()) to this Attendance Request.
    """
    employee = leave_doc.employee
    half_day_date = leave_doc.half_day_date

    draft_ar_name = _find_attendance_request(employee, half_day_date, docstatus_filter=0)

    if draft_ar_name:
        # Happy path: submit the existing draft.
        try:
            ar = frappe.get_doc("Attendance Request", draft_ar_name)
            ar.flags.ignore_permissions = True
            ar.submit()
            frappe.msgprint(
                _("Attendance Request {0} submitted for {1} (Half Day) on {2}.").format(
                    frappe.bold(ar.name),
                    frappe.bold(leave_doc.employee_name),
                    frappe.bold(str(half_day_date)),
                ),
                indicator="green",
                title=_("Attendance Request Submitted"),
            )
        except Exception:
            frappe.log_error(
                message=frappe.get_traceback(),
                title="Failed to submit Attendance Request {0}".format(draft_ar_name),
            )
            frappe.msgprint(
                _("Could not submit Attendance Request {0}. "
                  "Please check the Error Log.").format(frappe.bold(draft_ar_name)),
                indicator="orange",
                title=_("Submission Failed"),
            )
    else:
        # Fallback: draft was deleted or never created — create + submit directly.
        already_submitted = _find_attendance_request(
            employee, half_day_date, docstatus_filter=1
        )
        if already_submitted:
            return  # Already submitted by another path, nothing to do.

        _create_and_submit_attendance_request(leave_doc)


def _create_and_submit_attendance_request(leave_doc):
    """
    Fallback: create and immediately submit an Attendance Request.
    Used when the draft AR created in after_insert is missing.
    """
    employee = leave_doc.employee
    half_day_date = leave_doc.half_day_date
    company = leave_doc.company

    # Overlap guard — same as in _create_draft_attendance_request.
    overlapping = _has_overlapping_ar(employee, half_day_date)
    if overlapping:
        frappe.msgprint(
            _(
                "Could not auto-create Attendance Request for {0} on {1} — "
                "overlaps with existing request {2}."
            ).format(
                frappe.bold(leave_doc.employee_name),
                frappe.bold(str(half_day_date)),
                frappe.bold(overlapping),
            ),
            indicator="orange",
            title=_("Overlapping Attendance Request"),
        )
        return

    try:
        ar = frappe.new_doc("Attendance Request")
        ar.employee = employee
        ar.company = company
        ar.from_date = half_day_date
        ar.to_date = half_day_date
        ar.half_day = 1
        ar.half_day_date = half_day_date
        ar.reason = "On Duty"
        ar.explanation = _("Auto-created from Half Day Leave Application {0}").format(
            leave_doc.name
        )
        ar.flags.ignore_permissions = True
        ar.insert()
        ar.submit()

        frappe.msgprint(
            _("Attendance Request {0} auto-created for {1} (Half Day) on {2}.").format(
                frappe.bold(ar.name),
                frappe.bold(leave_doc.employee_name),
                frappe.bold(str(half_day_date)),
            ),
            indicator="green",
            title=_("Attendance Request Created"),
        )

    except Exception:
        frappe.log_error(
            message=frappe.get_traceback(),
            title="Auto Attendance Request failed for Leave {0}".format(leave_doc.name),
        )
        frappe.msgprint(
            _("Could not auto-create Attendance Request for {0} on {1}. "
              "Please check the Error Log.").format(
                frappe.bold(leave_doc.employee_name),
                frappe.bold(str(half_day_date)),
            ),
            indicator="orange",
            title=_("Auto Attendance Request Failed"),
        )


def _cancel_attendance_request(leave_doc):
    """
    Cancel all non-cancelled Attendance Requests for this employee + date.

    Submitted ARs: properly cancelled via AR.cancel() which also cancels
    any attendance records linked via the attendance_request field.

    Draft ARs: deleted (no attendance is linked to drafts, safe to remove).

    Note on Leave Application's own cancel_attendance():
    That method runs BEFORE this hook (standard hooks fire first) and sets
    attendance docstatus=2 directly. AR.on_cancel looks for attendance with
    docstatus=1, so no double-cancellation occurs.
    """
    employee = leave_doc.employee
    half_day_date = leave_doc.half_day_date

    # Cancel submitted Attendance Requests.
    submitted = frappe.get_all(
        "Attendance Request",
        filters={
            "employee": employee,
            "from_date": half_day_date,
            "to_date": half_day_date,
            "half_day": 1,
            "half_day_date": half_day_date,
            "docstatus": 1,
        },
        fields=["name"],
    )
    for req in submitted:
        try:
            frappe.get_doc("Attendance Request", req.name).cancel()
        except Exception:
            frappe.log_error(
                message=frappe.get_traceback(),
                title="Failed to cancel Attendance Request {0}".format(req.name),
            )
            frappe.msgprint(
                _("Could not cancel Attendance Request {0}. "
                  "Please cancel it manually.").format(frappe.bold(req.name)),
                indicator="orange",
            )

    # Delete any lingering draft Attendance Request.
    draft_name = _find_attendance_request(employee, half_day_date, docstatus_filter=0)
    if draft_name:
        _safe_delete_ar(draft_name, "leave cancelled")


def _delete_draft_attendance_request(leave_doc):
    """
    Called from on_trash when a draft leave is deleted.
    Removes the corresponding draft AR (no attendance linked → safe to delete).
    Submitted ARs are intentionally left alone.
    """
    draft_name = _find_attendance_request(
        leave_doc.employee, leave_doc.half_day_date, docstatus_filter=0
    )
    if draft_name:
        _safe_delete_ar(draft_name, "leave trashed")
