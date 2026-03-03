import frappe
from frappe import _
from frappe.utils import getdate, date_diff

BATCH_SIZE = 100
BG_THRESHOLD = 500  # Records above this count get queued as background job


@frappe.whitelist()
def get_attendance_count(from_date, to_date):
    """
    Returns count breakdown of attendance records in the given date range.
    Called when user clicks 'Preview' before deleting.
    """
    _validate_dates(from_date, to_date)

    filters = {"attendance_date": ["between", [from_date, to_date]]}

    total = frappe.db.count("Attendance", filters=filters)

    # Breakdown by docstatus so the user knows what will be cancelled vs deleted
    draft_count = frappe.db.count(
        "Attendance", filters={**filters, "docstatus": 0}
    )
    submitted_count = frappe.db.count(
        "Attendance", filters={**filters, "docstatus": 1}
    )
    cancelled_count = frappe.db.count(
        "Attendance", filters={**filters, "docstatus": 2}
    )

    return {
        "total": total,
        "draft": draft_count,
        "submitted": submitted_count,
        "cancelled": cancelled_count,
    }


@frappe.whitelist()
def bulk_delete_attendance(from_date, to_date):
    """
    Delete all Attendance records in the given date range.

    Strategy:
    - Validates date range and permissions.
    - For <= BG_THRESHOLD records: runs synchronously and returns result.
    - For > BG_THRESHOLD records: enqueues as a background (long) job so the
      HTTP request doesn't time out.
    """
    frappe.only_for(["System Manager", "HR Manager"])
    _validate_dates(from_date, to_date)

    total = frappe.db.count(
        "Attendance",
        filters={"attendance_date": ["between", [from_date, to_date]]},
    )

    if total == 0:
        return {"status": "done", "deleted": 0, "failed": 0, "errors": []}

    if total > BG_THRESHOLD:
        # Enqueue so the browser doesn't time out on large datasets.
        # Capture the session user NOW — frappe.session.user is not available
        # inside the background worker, so we pass it explicitly.
        triggered_by = frappe.session.user
        job_name = f"bulk_delete_attendance_{from_date}_{to_date}"
        frappe.enqueue(
            "attendance_customization.attendance_customization.page.bulk_delete_attendance.bulk_delete_attendance._do_bulk_delete",
            queue="long",
            timeout=7200,
            job_name=job_name,
            from_date=from_date,
            to_date=to_date,
            notify_user=triggered_by,
        )
        return {
            "status": "queued",
            "total": total,
            "message": _(
                "{0} records queued for deletion. A system notification will appear when complete."
            ).format(total),
        }

    # Small enough to handle synchronously
    result = _do_bulk_delete(from_date, to_date, notify_user=frappe.session.user)
    return {"status": "done", **result}


def _do_bulk_delete(from_date, to_date, notify_user=None):
    """
    Core deletion loop.  Fetches records in BATCH_SIZE chunks and deletes them.
    Submitted records are cancelled first. Each batch is committed separately
    to avoid a single giant transaction that could lock the table.

    notify_user: the Frappe user to send the realtime completion event to.
                 Must be captured BEFORE enqueuing (frappe.session.user is not
                 available inside a background worker).
    """
    deleted = 0
    failed = 0
    errors = []
    # Track names that failed so we never re-attempt them and loop forever.
    failed_names = set()

    while True:
        # Always re-query from scratch (no OFFSET) because successfully deleted
        # rows disappear each iteration.  Exclude already-failed names so a
        # persistent error on one record doesn't cause an infinite loop.
        extra_filters = {"attendance_date": ["between", [from_date, to_date]]}
        if failed_names:
            extra_filters["name"] = ["not in", list(failed_names)]

        records = frappe.db.get_list(
            "Attendance",
            fields=["name", "docstatus", "employee", "attendance_date", "employee_name"],
            filters=extra_filters,
            limit=BATCH_SIZE,
            order_by="name asc",
        )

        if not records:
            break  # All done (or only failed ones remain)

        for record in records:
            try:
                if record.docstatus == 1:
                    # Must cancel submitted docs before deleting
                    doc = frappe.get_doc("Attendance", record.name)
                    doc.flags.ignore_permissions = True
                    doc.cancel()

                frappe.delete_doc(
                    "Attendance",
                    record.name,
                    force=True,
                    ignore_missing=True,
                    ignore_permissions=True,
                )
                deleted += 1

            except Exception as exc:
                failed += 1
                failed_names.add(record.name)
                err_detail = {
                    "name": record.name,
                    "employee": record.get("employee_name") or record.get("employee"),
                    "date": str(record.get("attendance_date")),
                    "error": str(exc),
                }
                errors.append(err_detail)
                frappe.log_error(
                    message=str(exc),
                    title=f"Bulk Delete Attendance: {record.name}",
                )

        # Commit after each batch to release locks promptly
        frappe.db.commit()

    if failed:
        summary = "\n".join(
            f"{e['name']} ({e['date']}): {e['error']}" for e in errors[:50]
        )
        frappe.log_error(
            message=f"Deleted: {deleted}, Failed: {failed}\n\n{summary}",
            title="Bulk Delete Attendance — Summary",
        )

    # Send a realtime notification so the UI can update (critical for background jobs).
    # notify_user must be passed explicitly — frappe.session.user is None in workers.
    target_user = notify_user or frappe.session.user
    if target_user:
        frappe.publish_realtime(
            "bulk_delete_attendance_done",
            {"deleted": deleted, "failed": failed},
            user=target_user,
        )

    return {
        "deleted": deleted,
        "failed": failed,
        "errors": errors[:20],  # Cap response size
    }


# ── Helpers ─────────────────────────────────────────────────────────────────

def _validate_dates(from_date, to_date):
    """Raise descriptive errors for invalid date inputs."""
    try:
        from_dt = getdate(from_date)
    except Exception:
        frappe.throw(_("Invalid From Date: {0}").format(from_date), title=_("Validation Error"))

    try:
        to_dt = getdate(to_date)
    except Exception:
        frappe.throw(_("Invalid To Date: {0}").format(to_date), title=_("Validation Error"))

    if from_dt > to_dt:
        frappe.throw(
            _("From Date ({0}) cannot be after To Date ({1}).").format(from_date, to_date),
            title=_("Invalid Date Range"),
        )

    days = date_diff(to_dt, from_dt)
    if days > 366:
        frappe.throw(
            _("Date range cannot exceed 366 days. Please split into smaller batches."),
            title=_("Date Range Too Large"),
        )
