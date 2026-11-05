"""Complaint lifecycle workflow (CF-09): allowed transitions + role gates."""
from __future__ import annotations

WARD = {"super_admin", "state_admin", "district_admin", "municipal_admin", "ward_admin"}
DEPT = {"super_admin", "state_admin", "district_admin", "municipal_admin"}

# current_status -> {target_status: allowed_roles}
COMPLAINT_TRANSITIONS: dict[str, dict[str, set[str]]] = {
    "received": {"under_review": WARD},
    "under_review": {"inspection_scheduled": WARD, "in_progress": WARD,
                     "awaiting_verification": DEPT},
    "inspection_scheduled": {"in_progress": WARD, "awaiting_verification": DEPT},
    "in_progress": {"awaiting_verification": DEPT},
    "awaiting_verification": {},
    "reopened": {"under_review": WARD, "in_progress": WARD},
    "resolved": {"closed": DEPT},
    "closed": {},
}

CLOSE_ROLES = DEPT
DEPT_PLUS = DEPT
PRIORITY_OVERRIDE_ROLES = DEPT
MAX_PRIORITY_SCORE = 100.0
VERIFY_ACTIONS = {"confirm", "reject"}


def can_transition(current: str, target: str, role: str) -> bool:
    return role in COMPLAINT_TRANSITIONS.get(current, {}).get(target, set())


def allowed_targets(current: str, role: str) -> list[str]:
    return [t for t, roles in COMPLAINT_TRANSITIONS.get(current, {}).items() if role in roles]


def allowed_actions_for(complaint_status: str, role: str,
                        has_resolution_evidence: bool = False) -> list[str]:
    acts = []
    if can_transition(complaint_status, "inspection_scheduled", role):
        acts.append("schedule_inspection")
    if can_transition(complaint_status, "in_progress", role):
        acts.append("start_repair")
    if can_transition(complaint_status, "awaiting_verification", role):
        acts.append("submit_resolution")
    if complaint_status in ("awaiting_verification", "resolved") and role in CLOSE_ROLES:
        acts.append("close_with_reason")
    if complaint_status in ("resolved", "closed", "awaiting_verification", "in_progress"):
        acts.append("escalate")
    acts += ["assign_department", "correct_category", "set_priority",
             "request_info", "mark_duplicate"]
    return acts
