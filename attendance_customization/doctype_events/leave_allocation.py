from hrms.hr.doctype.leave_allocation.leave_allocation import LeaveAllocation


class CustomLeaveAllocation(LeaveAllocation):
    def validate_lwp(self):
        """
        Override HRMS validation to allow Leave Allocation for
        Leave Without Pay types like Loss of Pay (LOP).
        """
        pass
