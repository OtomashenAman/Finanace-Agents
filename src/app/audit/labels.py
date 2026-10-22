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
    ENTITIES = "entities"
    GOVERNANCE = "governance"
    AUDIT = "audit"


# event_type prefix -> category
_PREFIXES: dict[str, AuditCategory] = {
    "auth.": AuditCategory.SECURITY,
    "user.": AuditCategory.USERS,
    "run.": AuditCategory.RUNS,
    "data_source.": AuditCategory.DATA_SOURCES,
    "integration.": AuditCategory.DATA_SOURCES,
    "agent.": AuditCategory.AGENTS,
    "entity.": AuditCategory.ENTITIES,
    "governance.": AuditCategory.GOVERNANCE,
    "audit.": AuditCategory.AUDIT,
    "jobs.": AuditCategory.AUDIT,
}

FAILURE_EVENTS = frozenset(
    {
        "auth.login_failed",
        "auth.login_blocked",
        "auth.account_locked",
        "auth.refresh_reuse_detected",
        "auth.password_change_failed",
        "data_source.authorization_failed",
        "run.validation_failed",
        "run.rejected",
        "run.writeback_failed",
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
    "auth.password_changed": lambda d, s: "Changed their own password",
    "auth.password_change_failed": lambda d, s: "Password change refused (wrong current password)",
    "auth.password_reset_requested": lambda d, s: (
        "Asked for a password reset"
        + ("" if d.get("known", True) else f" for unknown {d.get('email')}")
    ),
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
        f"Approved {d.get('run')}"
        + (" (own run)" if d.get("self_review") else "")
        + (f" on behalf of {d['on_behalf_of']}" if d.get("on_behalf_of") else "")
    ),
    "run.approval_recorded": lambda d, s: (
        f"Approved {d.get('run')} ({d.get('approvals')} approvals, more needed)"
    ),
    "run.rejected": lambda d, s: f"Rejected {d.get('run')}",
    "run.changes_requested": lambda d, s: f"Requested changes on {d.get('run')}",
    "run.deleted": lambda d, s: f"Deleted draft {d.get('run')}",
    "run.evidence_exported": lambda d, s: f"Downloaded the evidence pack of {d.get('run')}",
    "run.writeback_requested": lambda d, s: f"Asked to write {d.get('run')} back to QuickBooks",
    "run.writeback_posted": lambda d, s: (
        f"Created QuickBooks bill {d.get('bill_id')} for {d.get('run')}"
        if d.get("created")
        else f"Noted the approval of {d.get('run')} on QuickBooks bill {d.get('bill_id')}"
    ),
    "run.writeback_failed": lambda d, s: (
        f"QuickBooks write-back of {d.get('run')} failed: {d.get('error')}"
    ),
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
    "entity.created": lambda d, s: f"Created legal entity {d.get('code')} · {d.get('name')}",
    "entity.updated": lambda d, s: (
        f"Updated legal entity {d.get('code')}: "
        + ", ".join(
            f"{k.replace('_', ' ')} → {v}" for k, v in d.items() if k not in ("entity_id", "code")
        )
    ),
    "user.entities_updated": lambda d, s: (
        f"Changed legal entities of {s}: " + (", ".join(d.get("entities", [])) or "none")
    ),
    "governance.settings_updated": lambda d, s: (
        "Admin self-approval "
        + ("allowed" if d.get("self_approval") else "turned off (full maker-checker)")
    ),
    "governance.policy_updated": lambda d, s: f"Saved thresholds {d.get('version')}",
    "governance.delegation_created": lambda d, s: (
        f"{d.get('delegate')} may approve for {d.get('delegator')} "
        f"({str(d.get('starts_at', ''))[:10]} to {str(d.get('ends_at', ''))[:10]})"
    ),
    "governance.delegation_cancelled": lambda d, s: "Cancelled an approval delegation",
    "governance.approval_matrix_updated": lambda d, s: (
        f"Changed the approval matrix of {d.get('agent')} ({len(d.get('tiers', []))} tiers)"
    ),
    "audit.exported": lambda d, s: f"Exported {d.get('rows')} audit events",
    "audit.purged": lambda d, s: (
        f"Retention purge removed {d.get('removed')} events older than "
        f"{str(d.get('cutoff', ''))[:10]}"
    ),
    "jobs.retried": lambda d, s: f"Retried a failed {d.get('kind')} job",
}


def describe(event_type: str, details: Mapping[str, Any], subject: str | None) -> str:
    text = _TEXT.get(event_type)
    if text is None:
        return event_type
    try:
        return text(details, subject or "a deleted user")
    except (AttributeError, TypeError, ValueError):  # unexpected details shape from old events
        return event_type
