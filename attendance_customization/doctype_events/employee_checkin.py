import frappe
from frappe.utils import getdate


def after_insert(doc, method):
    """
    Fires every time an Employee Checkin record is inserted.

    PRIMARY JOB:
        When a Half Day attendance already exists (submitted), link this checkin
        to it and set in_time/out_time so mark_attendance doesn't reprocess it.

    PAIR REQUIREMENT — HD/P vs HD/A:
        Valid attendance for the working half requires BOTH an IN and an OUT punch.
        This function keeps half_day_status in sync with the resulting pair state
        EVERY time a checkin arrives — not just the first time.

        Two branches depending on whether leave_application is already set:

        BRANCH A — leave_application IS set on attendance:
            Sync half_day_status with the resulting pair state.
            - Now has IN + OUT → half_day_status = "Present" (HD/P).
            - Only one of the pair → half_day_status = "Absent"  (HD/A).
            This correctly handles:
              • Leave was approved, only IN existed → "Absent". OUT arrives → "Present".
              • Leave was approved, both existed → already "Present", no change.

        BRANCH B — leave_application NOT set (6 AM checker removed it):
            Biometric-delay case. Re-link leave_application only when pair is complete.
            - Pair complete → restore leave_application + half_day_status = "Present".
            - Pair incomplete → do nothing; wait for the other punch.

        Untyped checkins (log_type blank): can't determine pair from type alone,
        so if the attendance already has in_time set, treat the untyped punch as
        the OUT (and vice versa). If neither time is set, treat untyped as valid.

    FOR PRE-LEAVE CHECKINS:
        Checkins that arrive before leave approval have no Half Day attendance yet.
        leave_application.on_update_after_submit handles that retroactively.

    EDGE CASES:
    - doc.time is None                      → return early.
    - No Half Day attendance for date       → return early (normal working day).
    - log_type IN  but in_time  already set → skip time update, still evaluate pair.
    - log_type OUT but out_time already set → skip time update, still evaluate pair.
    - log_type missing                      → link only; treat as valid if any time exists.
    """
    if not doc.time:
        return

    checkin_date = getdate(doc.time)

    attendance = frappe.db.get_value(
        "Attendance",
        {
            "employee": doc.employee,
            "attendance_date": checkin_date,
            "status": "Half Day",
            "docstatus": 1,
        },
        ["name", "in_time", "out_time", "leave_application", "half_day_status"],
        as_dict=True,
    )

    if not attendance:
        return

    update = {}

    # ── Step 1: update in_time / out_time ────────────────────────────────────
    if doc.log_type == "IN" and not attendance.in_time:
        update["in_time"] = doc.time
    elif doc.log_type == "OUT" and not attendance.out_time:
        update["out_time"] = doc.time

    # ── Step 2: compute resulting pair state after this update ────────────────
    # Use the times that will be on the attendance AFTER the update is saved.
    resulting_in = update.get("in_time") or attendance.in_time
    resulting_out = update.get("out_time") or attendance.out_time

    if not doc.log_type:
        # Untyped checkin: device doesn't send IN/OUT — can't validate pair type.
        # Treat as valid immediately (benefit of the doubt for legacy devices).
        has_pair = True
    else:
        has_pair = bool(resulting_in and resulting_out)

    # ── Step 3: sync half_day_status with pair state ──────────────────────────
    if attendance.leave_application:
        # Leave is already linked. Just keep half_day_status in sync with pair.
        if has_pair and attendance.half_day_status != "Present":
            update["half_day_status"] = "Present"
        elif not has_pair and attendance.half_day_status == "Present":
            # Pair is now incomplete (e.g. only IN arrived, no OUT yet) → HD/A.
            update["half_day_status"] = "Absent"

    else:
        # leave_application was removed by the 6 AM checker (biometric delay).
        # Restore it only when the pair is complete — don't restore on a single punch.
        if has_pair:
            leave = frappe.db.get_value(
                "Leave Application",
                {
                    "employee": doc.employee,
                    "half_day_date": checkin_date,
                    "half_day": 1,
                    "status": "Approved",
                    "docstatus": 1,
                },
                ["name", "leave_type"],
                as_dict=True,
            )
            if leave:
                update["leave_application"] = leave.name
                update["leave_type"] = leave.leave_type
                update["half_day_status"] = "Present"

    # ── Step 4: persist ───────────────────────────────────────────────────────
    if update:
        frappe.db.set_value("Attendance", attendance.name, update)

    frappe.db.set_value("Employee Checkin", doc.name, "attendance", attendance.name)

    frappe.logger().info(
        "Half Day attendance {}: updated {} from Employee Checkin {}".format(
            attendance.name,
            list(update.keys()) if update else ["linked only"],
            doc.name,
        )
    )
