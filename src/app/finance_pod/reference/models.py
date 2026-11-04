"""Reference data the agents work from: cost centres, labs, projects, grants, budgets,
catalogue / contract prices, approved vendors and the authority matrix.

Loaded from a workbook (rows are matched on their code and updated; rows not in the file
stay, so an "Active" column retires one). Requests copy the codes they use, so later
changes here never rewrite a request's history.
"""

from datetime import date
from decimal import Decimal
from enum import StrEnum

from sqlalchemy import CheckConstraint, Numeric, String, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from src.app.common.models import (
    Base,
    TimestampMixin,
    UUIDPrimaryKeyMixin,
    enum_check,
    string_enum,
)


class _Coded(UUIDPrimaryKeyMixin, TimestampMixin):
    code: Mapped[str] = mapped_column(String(40), unique=True)
    name: Mapped[str] = mapped_column(String(200))
    active: Mapped[bool] = mapped_column(default=True, server_default=text("true"))


class FpCostCentre(_Coded, Base):
    __tablename__ = "fpod_cost_centres"

    # The budget owner: a Finance Admin's email (approvals route to them)
    owner_email: Mapped[str | None] = mapped_column(String(320))


class FpLab(_Coded, Base):
    __tablename__ = "fpod_labs"

    cost_centre_code: Mapped[str | None] = mapped_column(String(40))


class FpProject(_Coded, Base):
    __tablename__ = "fpod_projects"

    cost_centre_code: Mapped[str | None] = mapped_column(String(40))
    grant_code: Mapped[str | None] = mapped_column(String(40))


class FpGrant(_Coded, Base):
    __tablename__ = "fpod_grants"

    sponsor: Mapped[str | None] = mapped_column(String(200))
    cost_centre_code: Mapped[str | None] = mapped_column(String(40))
    owner_email: Mapped[str | None] = mapped_column(String(320))  # principal investigator
    start_date: Mapped[date | None]
    end_date: Mapped[date | None]
    award_amount: Mapped[Decimal | None] = mapped_column(Numeric(18, 2))
    # Expense categories the sponsor doesn't allow (lowercase), e.g. ["alcohol", "furniture"]
    unallowable_categories: Mapped[list[str]] = mapped_column(
        JSONB, default=list, server_default=text("'[]'::jsonb")
    )


class FpBudget(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """One budget line: a fiscal year's amount for a cost centre or a grant (optionally one
    expense category). Remaining = amount - committed - spent."""

    __tablename__ = "fpod_budgets"
    __table_args__ = (
        CheckConstraint("(cost_centre_code IS NULL) <> (grant_code IS NULL)", name="one_holder"),
        UniqueConstraint(
            "fiscal_year",
            "cost_centre_code",
            "grant_code",
            "category",
            postgresql_nulls_not_distinct=True,
        ),
    )

    fiscal_year: Mapped[int]
    cost_centre_code: Mapped[str | None] = mapped_column(String(40))
    grant_code: Mapped[str | None] = mapped_column(String(40))
    category: Mapped[str | None] = mapped_column(String(64))
    amount: Mapped[Decimal] = mapped_column(Numeric(18, 2))
    committed: Mapped[Decimal] = mapped_column(Numeric(18, 2), default=0, server_default="0")
    spent: Mapped[Decimal] = mapped_column(Numeric(18, 2), default=0, server_default="0")


class FpCatalogueItem(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """An item at a contract price from a vendor."""

    __tablename__ = "fpod_catalogue_items"

    item_code: Mapped[str] = mapped_column(String(40), unique=True)
    description: Mapped[str] = mapped_column(String(500))
    category: Mapped[str | None] = mapped_column(String(64))
    unit: Mapped[str | None] = mapped_column(String(20))
    unit_price: Mapped[Decimal] = mapped_column(Numeric(18, 2))
    vendor_code: Mapped[str | None] = mapped_column(String(40))
    contract_ref: Mapped[str | None] = mapped_column(String(80))
    contract_end: Mapped[date | None]
    active: Mapped[bool] = mapped_column(default=True, server_default=text("true"))


class VendorStatus(StrEnum):
    APPROVED = "approved"
    BLOCKED = "blocked"


class FpVendor(_Coded, Base):
    """The approved vendor list. Bank details are never imported: they only arrive through
    the onboarding portal and need a call-back and a second approver (Phase 1.5)."""

    __tablename__ = "fpod_vendors"
    __table_args__ = (enum_check("status", VendorStatus),)

    email: Mapped[str | None] = mapped_column(String(320))
    tax_id: Mapped[str | None] = mapped_column(String(40))
    status: Mapped[VendorStatus] = mapped_column(
        string_enum(VendorStatus, 16), default=VendorStatus.APPROVED
    )
    categories: Mapped[list[str]] = mapped_column(
        JSONB, default=list, server_default=text("'[]'::jsonb")
    )


class AuthorityScope(StrEnum):
    REQUEST = "request"  # budget approval of a purchase request
    PO = "po"  # buyer approval of a purchase order


class FpAuthorityTier(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Authority matrix: from `min_amount` up (optionally for one cost centre), who approves.
    Replaced as a whole on import."""

    __tablename__ = "fpod_authority_tiers"
    __table_args__ = (
        enum_check("scope", AuthorityScope),
        CheckConstraint("min_amount >= 0", name="min_amount"),
    )

    scope: Mapped[AuthorityScope] = mapped_column(string_enum(AuthorityScope, 16))
    cost_centre_code: Mapped[str | None] = mapped_column(String(40))
    min_amount: Mapped[Decimal] = mapped_column(Numeric(18, 2))
    approver_email: Mapped[str] = mapped_column(String(320))
    capacity: Mapped[str] = mapped_column(String(60))  # e.g. "Budget owner", "Dean", "Buyer"
