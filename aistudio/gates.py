"""E13: spending gates. Pure functions, no I/O. Raises GateError with a clear message; returns None when allowed."""
STOP_LOSS = 1.30
MAX_ATTEMPTS = 3


class GateError(Exception):
    pass


def check_run(budget, spent, planned, attempts, max_attempts=MAX_ATTEMPTS, override=False, today_spent=0.0, daily_limit=None):
    """budget: dict with "approved" (bool) and "stop_loss" (float).  spent: total so far.  planned: cost of this run.
    attempts: completed final attempts of this shot so far."""
    if not budget or not budget.get("approved"):
        raise GateError("budget not approved")
    if planned < 0:
        raise GateError("negative cost")
    if attempts >= max_attempts and not override:
        raise GateError(f"{attempts} attempts already (max {max_attempts}); change the approach or override")
    if spent + planned > budget["stop_loss"] and not override:
        raise GateError(f"stop-loss: spent {spent:.2f} + {planned:.2f} exceeds {budget['stop_loss']:.2f}")
    if daily_limit is not None and today_spent + planned > daily_limit and not override:
        raise GateError(f"daily limit {daily_limit:.2f} would be exceeded")


def stop_loss_for(estimate, factor=STOP_LOSS):
    return round(estimate * factor, 2)
