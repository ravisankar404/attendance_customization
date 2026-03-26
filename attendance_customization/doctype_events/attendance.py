import frappe
from frappe.utils import getdate, get_first_day, get_last_day, now_datetime


# ─────────────────────────────────────────────
# Document event hooks (registered in hooks.py)
# ─────────────────────────────────────────────

def on_submit(doc, method):
    """
    Handle attendance submission - mark late strike as processed.
    """
    if doc.status == "Present" and doc.late_entry == 1 and not doc.strike_processed:
        frappe.db.set_value("Attendance", doc.name, "strike_processed", 1)
        frappe.db.commit()


def validate(doc, method):
    """
    Fires on every attendance save/insert (draft only).

    Order matters:
    1. _enforce_checkin_pair_rule  — demote Present→Absent if only one checkin exists.
    2. _ensure_half_day_attendance — promote to Half Day if an approved half-day leave
                                      exists, then HD/P vs HD/A based on pair presence.
    3. Late strike count update.
    """
    _enforce_checkin_pair_rule(doc)
    _ensure_half_day_attendance(doc)

    if doc.status == "Present" and doc.late_entry == 1:
        update_late_strike_count(doc)


# ─────────────────────────────────────────────
# Checkin pair enforcement
# ─────────────────────────────────────────────

def _enforce_checkin_pair_rule(doc):
    """
    Valid attendance from the biometric system requires a matched IN + OUT pair.
    If only one punch exists the employee either forgot to check out, or the
    device missed one swipe — either way salary should NOT be paid for that half.

    RULE:
      - in_time set  AND  out_time set  → valid pair → no change.
      - in_time set  XOR  out_time set  → incomplete → force Absent.
      - neither set                     → manual/leave-created attendance → skip.

    SKIPPED:
      - Half Day: handled downstream by _ensure_half_day_attendance which reads
        in_time/out_time directly and decides HD/P vs HD/A.
      - On Leave / Work From Home: intentional statuses set by HR — never override.
      - Penalty records (custom_late_penalty_applied=1): managed by
        late_strike_processor — don't interfere.
      - No checkin data at all (both times blank): manual attendance → accept as-is.
    """
    if doc.status in ("On Leave", "Work From Home", "Half Day"):
        return
    if doc.get("custom_late_penalty_applied"):
        return
    # No biometric data — manual or leave-created record, nothing to enforce.
    if not doc.in_time and not doc.out_time:
        return
    # Incomplete pair → Absent.
    if not (doc.in_time and doc.out_time):
        doc.status = "Absent"


# ─────────────────────────────────────────────
# Half-day leave attendance correction
# ─────────────────────────────────────────────

def _ensure_half_day_attendance(doc):
    """
    Auto-correct attendance on half-day leave dates so the Monthly Attendance
    Sheet shows the right status regardless of how attendance was created.

    CASES HANDLED (evaluated AFTER _enforce_checkin_pair_rule runs):

      in_time + out_time both set + approved half-day leave
          → "Half Day" + leave_application + half_day_status="Present"   (HD/P) ✓
          Employee worked the other half → full pay, 0.5 leave consumed.

      Only one of in_time/out_time set + approved half-day leave
          → "Half Day" + no leave_application + half_day_status="Absent" (HD/A) ✓
          _enforce_checkin_pair_rule already set status="Absent"; we preserve that
          intent. 0.5 leave consumed + 0.5 salary deduction = L/A.

      No checkin times at all + approved half-day leave
          → "Half Day" + leave_application + half_day_status="Present"   (HD/P, optimistic)
          Attendance was created from leave approval before checkins arrived.
          The 6 AM checker will flip to HD/A the next morning if no valid
          IN+OUT pair arrives by then.

    HRMS v15 Monthly Attendance Sheet reads half_day_status (NOT leave_application):
      half_day_status="Present" → HD/P  (other half worked)
      half_day_status="Absent"  → HD/A  (other half missed)

    SKIPPED:
      - Already fully correct (Half Day + leave_application + half_day_status=Present
        + both times set): fast exit avoids a DB query.
      - On Leave / Work From Home: intentional statuses, never override.
      - Penalty records: managed by late_strike_processor.
      - Missing employee or attendance_date: guard against bad data.
    """
    # Fast exit: already correct — skip DB query.
    #
    # Two safe states that need no re-evaluation:
    #   1. Half Day + leave linked + HD/P + BOTH times set
    #      → pair confirmed, nothing to change.
    #   2. Half Day + leave linked + HD/P + NO times set
    #      → leave-created attendance, checkins not linked yet.
    #        6 AM checker owns the no-checkin correction — don't interfere here.
    #
    # The only case that falls through: one time set but not the other
    # (e.g. in_time set by _link_checkins but out_time still missing).
    # That needs re-evaluation so we can flip to HD/A.
    if (doc.status == "Half Day"
            and doc.leave_application
            and doc.get("half_day_status") == "Present"):
        has_both = bool(doc.in_time and doc.out_time)
        has_neither = not doc.in_time and not doc.out_time
        if has_both or has_neither:
            return

    if doc.status in ("On Leave", "Work From Home"):
        return

    if doc.get("custom_late_penalty_applied"):
        return

    if not doc.employee or not doc.attendance_date:
        return

    leave = frappe.db.get_value(
        "Leave Application",
        {
            "employee": doc.employee,
            "half_day_date": doc.attendance_date,
            "half_day": 1,
            "status": "Approved",
            "docstatus": 1,
        },
        ["name", "leave_type"],
        as_dict=True,
    )

    if not leave:
        return

    # Upgrade to Half Day regardless of what HRMS computed.
    doc.status = "Half Day"
    doc.leave_type = leave.leave_type

    if doc.in_time and doc.out_time:
        # Valid IN+OUT pair → employee worked the other half → HD/P.
        doc.leave_application = leave.name
        doc.half_day_status = "Present"
    elif doc.in_time or doc.out_time:
        # Incomplete pair (only one punch) → employee didn't complete the working half.
        # Clear leave_application so payroll and 6 AM checker don't count this as
        # leave-covered. half_day_status="Absent" → Monthly Sheet shows HD/A (L/A).
        doc.leave_application = None
        doc.half_day_status = "Absent"
    else:
        # No checkin data yet — attendance was created from leave approval before
        # checkins were linked. Default to HD/P; 6 AM checker corrects if no
        # valid pair arrives by next morning.
        doc.leave_application = leave.name
        doc.half_day_status = "Present"


# ─────────────────────────────────────────────
# Late strike helpers (used by validate above
# and by late_strike_processor.py scheduled task)
# ─────────────────────────────────────────────

def update_late_strike_count(doc):
    """
    Update the late strike count for the current month on the doc object.
    Called from validate (real-time) and indirectly from the scheduled task.
    """
    attendance_date = getdate(doc.attendance_date)
    first_day = get_first_day(attendance_date)
    last_day = get_last_day(attendance_date)

    late_count = frappe.db.count("Attendance", filters={
        "employee": doc.employee,
        "attendance_date": ["between", [first_day, last_day]],
        "late_entry": 1,
        "status": "Present",
        "docstatus": 1
    })

    if doc.docstatus == 0:
        late_count += 1

    doc.late_strike_count = late_count

    month_year = attendance_date.strftime("%B %Y")
    ordinal = {1: "1st", 2: "2nd", 3: "3rd"}.get(late_count, "{}th".format(late_count))
    doc.late_incident_remark = "{} late arrival in {}".format(ordinal, month_year)

    if late_count >= 3:
        doc.late_incident_remark += " - WARNING: Exceeded monthly late arrival limit!"


def get_monthly_late_summary(employee, month=None, year=None):
    """
    Get late arrival summary for an employee for a specific month.
    """
    if not month or not year:
        today = getdate()
        month = today.month
        year = today.year

    first_day = getdate("{}-{:02d}-01".format(year, month))
    last_day = get_last_day(first_day)

    late_entries = frappe.get_all(
        "Attendance",
        filters={
            "employee": employee,
            "attendance_date": ["between", [first_day, last_day]],
            "late_entry": 1,
            "status": "Present",
            "docstatus": 1
        },
        fields=["name", "attendance_date", "late_incident_remark"],
        order_by="attendance_date asc"
    )

    return {
        "employee": employee,
        "month": first_day.strftime("%B %Y"),
        "late_count": len(late_entries),
        "late_entries": late_entries
    }
