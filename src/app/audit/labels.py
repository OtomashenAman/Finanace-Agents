"""Readable text for audit events ("Approved RUN-01006"), their category and outcome."""

from collections.abc import Callable, Mapping
from enum import StrEnum
from typing import Any


class AuditCategory(StrEnum):
    SECURITY = "security"
    USERS = "users"
    RUNS = "runs"
    DATA_SOURCES = "data_sources"
    AGENTS = "agents"
    AUDIT = "audit"


# event_type prefix -> category
_PREFIXES: dict[str, AuditCategory] = {
    "auth.": AuditCategory.SECURITY,
    "user.": AuditCategory.USERS,
    "run.": AuditCategory.RUNS,
    "data_source.": AuditCategory.DATA_SOURCES,
    "integration.": AuditCategory.DATA_SOURCES,
    "agent.": AuditCategory.AGENTS,
    "audit.": AuditCategory.AUDIT,
}

FAILURE_EVENTS = frozenset(
    {
        "auth.login_failed",
        "auth.login_blocked",
        "auth.account_locked",
        "auth.refresh_reuse_detected",
        "data_source.authorization_failed",
        "run.validation_failed",
        "run.rejected",
    }
)

_LOGIN_FAILURES = {
    "bad_password": "wrong password",
    "unknown_email": "unknown email",
    "inactive": "account deactivated",
}


def category_of(event_type: str) -> AuditCategory | None:
    return next((c for p, c in _PREFIXES.items() if event_type.startswith(p)), None)


def prefixes_of(category: AuditCategory) -> list[str]:
    return [p for p, c in _PREFIXES.items() if c == category]


Describe = Callable[[Mapping[str, Any], str], str]

# (details, subject) -> text; subject is the user an event is about, already resolved to a name
_TEXT: dict[str, Describe] = {
    "auth.login_success": lambda d, s: "Signed in",
    "auth.login_failed": lambda d, s: (
        f"Sign-in failed ({_LOGIN_FAILURES.get(d.get('reason', ''), d.get('reason', ''))})"
        + (f" for {d['email']}" if d.get("email") else "")
    ),
    "auth.login_blocked": lambda d, s: "Sign-in blocked: account is locked",
    "auth.account_locked": lambda d, s: "Account locked after repeated failed sign-ins",
    "auth.logout": lambda d, s: "Signed out",
    "auth.refresh_reuse_detected": lambda d, s: (
        "A reused session token was detected: that login's sessions were ended"
    ),
    "user.created": lambda d, s: f"Created user {d.get('email', s)} ({d.get('role', '')})",
    "user.updated": lambda d, s: (
        f"Updated {s}: "
        + ", ".join(f"{k.replace('_', ' ')} → {v}" for k, v in d.items() if k != "user_id")
    ),
    "user.deleted": lambda d, s: f"Deleted user {d.get('email', s)}",
    "user.password_reset": lambda d, s: f"Set a new password for {s}",
    "user.assignments_updated": lambda d, s: (
        f"Changed agent access of {s}: "
        + (", ".join(a.split(":")[0] for a in d.get("assignments", [])) or "none")
    ),
    "run.created": lambda d, s: f"Created {d.get('run')}",
    "run.source_linked": lambda d, s: f"Prefilled {d.get('run')} from a data source",
    "run.source_unlinked": lambda d, s: f"Unlinked {d.get('run')} from its data source",
    "run.document_added": lambda d, s: f"Attached {d.get('filename')} to {d.get('run')}",
    "run.document_removed": lambda d, s: f"Removed {d.get('filename')} from {d.get('run')}",
    "run.validation_failed": lambda d, s: f"Validation failed for {d.get('run')}",
    "run.analyzed": lambda d, s: f"Analyzed {d.get('run')}",
    "run.submitted": lambda d, s: f"Submitted {d.get('run')} for approval",
    "run.approved": lambda d, s: (
        f"Approved {d.get('run')}" + (" (own run)" if d.get("self_review") else "")
    ),
    "run.rejected": lambda d, s: f"Rejected {d.get('run')}",
    "run.changes_requested": lambda d, s: f"Requested changes on {d.get('run')}",
    "run.deleted": lambda d, s: f"Deleted draft {d.get('run')}",
    "data_source.authorization_started": lambda d, s: "Started connecting QuickBooks",
    "data_source.authorized": lambda d, s: "Connected a QuickBooks company",
    "data_source.authorization_failed": lambda d, s: (
        f"QuickBooks connection failed: {d.get('reason', '')}"
    ),
    "data_source.synced": lambda d, s: (
        "Synced QuickBooks: "
        + ", ".join(f"{n} {t.replace('_', ' ')}" for t, n in d.get("counts", {}).items())
    ),
    "data_source.app_updated": lambda d, s: "Changed the QuickBooks app credentials",
    "data_source.uploaded": lambda d, s: (
        f"Uploaded {d.get('filename')} ({d.get('imported')} {d.get('record_type', '')} records)"
    ),
    "data_source.deleted": lambda d, s: f"Removed data source {d.get('name')}",
    "integration.quickbooks_updated": lambda d, s: "Updated the shared QuickBooks app",
    "agent.activated": lambda d, s: f"Enabled agent {d.get('agent_key')}",
    "agent.deactivated": lambda d, s: f"Disabled agent {d.get('agent_key')}",
    "audit.exported": lambda d, s: f"Exported {d.get('rows')} audit events",
}


def describe(event_type: str, details: Mapping[str, Any], subject: str | None) -> str:
    text = _TEXT.get(event_type)
    if text is None:
        return event_type
    try:
        return text(details, subject or "a deleted user")
    except (AttributeError, TypeError, ValueError):  # unexpected details shape from old events
        return event_type
