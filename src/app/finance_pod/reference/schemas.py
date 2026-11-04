from datetime import date
from decimal import Decimal

from pydantic import BaseModel


class SheetResult(BaseModel):
    sheet: str
    title: str
    created: int
    updated: int
    removed: int = 0  # authority matrix: replaced as a whole


class ImportResult(BaseModel):
    sheets: list[SheetResult]
    warnings: list[str]


class CostCentreOut(BaseModel):
    code: str
    name: str
    owner_email: str | None
    active: bool


class LabOut(BaseModel):
    code: str
    name: str
    cost_centre_code: str | None
    active: bool


class ProjectOut(BaseModel):
    code: str
    name: str
    cost_centre_code: str | None
    grant_code: str | None
    active: bool


class GrantOut(BaseModel):
    code: str
    name: str
    sponsor: str | None
    cost_centre_code: str | None
    owner_email: str | None
    start_date: date | None
    end_date: date | None
    award_amount: Decimal | None
    unallowable_categories: list[str]
    active: bool


class BudgetOut(BaseModel):
    fiscal_year: int
    cost_centre_code: str | None
    grant_code: str | None
    category: str | None
    amount: Decimal
    committed: Decimal
    spent: Decimal
    remaining: Decimal


class CatalogueItemOut(BaseModel):
    item_code: str
    description: str
    category: str | None
    unit: str | None
    unit_price: Decimal
    vendor_code: str | None
    contract_ref: str | None
    contract_end: date | None
    active: bool


class VendorOut(BaseModel):
    code: str
    name: str
    email: str | None
    tax_id: str | None
    status: str
    categories: list[str]


class AuthorityTierOut(BaseModel):
    scope: str
    cost_centre_code: str | None
    min_amount: Decimal
    approver_email: str
    capacity: str


class ReferenceOut(BaseModel):
    cost_centres: list[CostCentreOut]
    labs: list[LabOut]
    projects: list[ProjectOut]
    grants: list[GrantOut]
    budgets: list[BudgetOut]
    catalogue: list[CatalogueItemOut]
    vendors: list[VendorOut]
    authority: list[AuthorityTierOut]
