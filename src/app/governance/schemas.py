import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field

from src.app.agent_catalog.agents.fields import FormField
from src.app.data_sources.records import Money


class OrgSettingsOut(BaseModel):
    allow_admin_self_approval: bool
    updated_at: datetime | None


class OrgSettingsUpdate(BaseModel):
    allow_admin_self_approval: bool


class PolicyVersionOut(BaseModel):
    version_label: str  # e.g. "ap_invoice/v3"; the code default is policy_version (v1)
    is_default: bool
    values: dict[str, Any]
    note: str | None
    created_at: datetime | None
    created_by: str | None


class PolicyOut(BaseModel):
    agent_key: str
    agent_name: str
    fields: list[FormField]
    current: PolicyVersionOut


class PolicyUpdate(BaseModel):
    values: dict[str, Any]
    note: str | None = Field(default=None, max_length=300)


class Approver(BaseModel):
    id: uuid.UUID
    full_name: str


class ApprovalTierIn(BaseModel):
    min_amount: Money = Field(ge=0)
    approvals_required: int = Field(ge=1, le=3)
    # Finance Admins allowed to approve this tier; empty = any Finance Admin
    approver_ids: list[uuid.UUID] = []


class ApprovalTierOut(BaseModel):
    min_amount: Money
    approvals_required: int
    approvers: list[Approver]  # empty = any Finance Admin


class ApprovalMatrixOut(BaseModel):
    agent_key: str
    agent_name: str
    amount_label: str | None  # what the tiers compare against, e.g. "Invoice total"
    tiers: list[ApprovalTierOut]  # ascending; none = one approval by any Finance Admin


class ApprovalMatrixUpdate(BaseModel):
    tiers: list[ApprovalTierIn] = Field(max_length=10)
