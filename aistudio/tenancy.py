"""Pure local models and policy evaluation for the future hosted tier."""
from dataclasses import dataclass
from enum import Enum


class Role(str, Enum):
    ORG_OWNER = "org_owner"
    ORG_ADMIN = "org_admin"
    ORG_BILLING = "org_billing"
    ORG_MEMBER = "org_member"
    WORKSPACE_EDITOR = "workspace_editor"
    WORKSPACE_REVIEWER = "workspace_reviewer"
    WORKSPACE_VIEWER = "workspace_viewer"
    AGENT = "agent"


@dataclass(frozen=True)
class Org:
    id: str
    name: str


@dataclass(frozen=True)
class Workspace:
    id: str
    org_id: str
    name: str


@dataclass(frozen=True)
class Member:
    user_id: str
    role: Role
    workspace_id: str = ""


@dataclass(frozen=True)
class SpendPolicy:
    approval_threshold_usd: float = 0.0
    monthly_cap_usd: float = 0.0
    allow_autopilot: bool = False
    agents_propose_only: bool = True


ACTION_VOCABULARY = frozenset({
    "approve_spend", "run_batch", "edit_docs", "comment", "view", "manage_keys",
    "manage_members", "delete_project",
})

_PERMISSIONS = {
    Role.ORG_OWNER: ACTION_VOCABULARY,
    Role.ORG_ADMIN: ACTION_VOCABULARY - {"manage_members"},
    Role.ORG_BILLING: frozenset({"view", "approve_spend"}),
    Role.ORG_MEMBER: frozenset({"view", "comment"}),
    Role.WORKSPACE_EDITOR: frozenset({"view", "run_batch", "edit_docs", "comment"}),
    Role.WORKSPACE_REVIEWER: frozenset({"view", "comment"}),
    Role.WORKSPACE_VIEWER: frozenset({"view"}),
    Role.AGENT: frozenset({"view", "run_batch", "edit_docs"}),
}


def can(role, action):
    if action not in ACTION_VOCABULARY:
        raise ValueError(f"unknown action: {action}")
    try:
        normalized = role if isinstance(role, Role) else Role(role)
    except (ValueError, TypeError):
        return False
    return action in _PERMISSIONS[normalized]


def evaluate(policy, actor_role, amount):
    """Return allow, needs_admin, or deny. amount is proposed spend against remaining monthly capacity."""
    amount = float(amount)
    if amount < 0:
        raise ValueError("amount must be nonnegative")
    if policy.monthly_cap_usd > 0 and amount > policy.monthly_cap_usd:
        return "deny"
    role = actor_role if isinstance(actor_role, Role) else Role(actor_role)
    if role == Role.AGENT and policy.agents_propose_only:
        return "needs_admin"
    if amount > policy.approval_threshold_usd or (amount > 0 and not policy.allow_autopilot):
        return "needs_admin"
    return "allow"
