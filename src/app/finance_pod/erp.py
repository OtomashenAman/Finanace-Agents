"""Where active vendors, issued POs and client accounts are created: the ERP.

FINANCE_POD_ERP=local (default): the Finance POD's own vendor master, PO register and client
accounts are the system of record; the reference is the Finance POD's own (vendor code, PO
number, client code).

FINANCE_POD_ERP=workday: Workday Resource Management (Submit Supplier, Submit Purchase
Order). Not connected yet: it needs the tenant URL, an integration system user / API
client with procurement scopes, and a test tenant to build against. Until then choosing it
refuses to activate a vendor or issue a PO, with that reason, instead of pretending.
"""

from dataclasses import dataclass
from decimal import Decimal
from typing import Protocol

from src.app.core.config import get_settings
from src.app.core.errors import AppError


class ErpNotReadyError(AppError):
    status_code = 503
    code = "erp_not_ready"


@dataclass(frozen=True)
class ErpVendor:
    code: str
    name: str
    email: str | None
    tax_id: str | None


@dataclass(frozen=True)
class ErpPoLine:
    description: str
    quantity: Decimal
    unit_price: Decimal


@dataclass(frozen=True)
class ErpPurchaseOrder:
    number: str
    vendor_code: str
    currency: str
    total: Decimal
    lines: list[ErpPoLine]
    coding: dict[str, str | None]


@dataclass(frozen=True)
class ErpInvoice:
    number: str  # ours, e.g. INV-00012
    vendor_code: str
    vendor_invoice_number: str
    po_number: str | None
    currency: str
    total: Decimal
    source_filename: str | None


@dataclass(frozen=True)
class ErpCustomer:
    code: str
    name: str
    billing_email: str
    tax_id: str | None
    currency: str
    credit_limit: Decimal | None
    payment_terms: str
    on_hold: bool


class Erp(Protocol):
    name: str

    async def upsert_customer(self, customer: ErpCustomer) -> str:
        """The ERP's reference for the client account (created, or updated in place)."""
        ...

    async def create_vendor(self, vendor: ErpVendor) -> str:
        """The ERP's reference for the new supplier."""
        ...

    async def create_po(self, po: ErpPurchaseOrder) -> str:
        """The ERP's reference for the issued PO."""
        ...

    async def create_invoice(self, invoice: ErpInvoice) -> str:
        """The ERP's reference for the supplier invoice (with its source document)."""
        ...


class LocalErp:
    """The Finance POD's own records are the system of record."""

    name = "local"

    async def upsert_customer(self, customer: ErpCustomer) -> str:
        return customer.code

    async def create_vendor(self, vendor: ErpVendor) -> str:
        return vendor.code

    async def create_po(self, po: ErpPurchaseOrder) -> str:
        return po.number

    async def create_invoice(self, invoice: ErpInvoice) -> str:
        return invoice.number


class WorkdayErp:
    name = "workday"

    def __init__(self) -> None:
        s = get_settings()
        missing = [
            label
            for label, value in (
                ("WORKDAY_BASE_URL", s.workday_base_url),
                ("WORKDAY_TENANT", s.workday_tenant),
                ("WORKDAY_CLIENT_ID", s.workday_client_id),
                ("WORKDAY_CLIENT_SECRET", s.workday_client_secret),
                ("WORKDAY_REFRESH_TOKEN", s.workday_refresh_token),
            )
            if not value
        ]
        self._reason = (
            f"Workday isn't configured ({', '.join(missing)} missing)."
            if missing
            else "The Workday connection (Submit Supplier / Submit Purchase Order) isn't built "
            "yet: it needs a Workday test tenant to build and verify against."
        )

    async def upsert_customer(self, customer: ErpCustomer) -> str:
        raise ErpNotReadyError(self._reason + " Set FINANCE_POD_ERP=local to keep working.")

    async def create_vendor(self, vendor: ErpVendor) -> str:
        raise ErpNotReadyError(self._reason + " Set FINANCE_POD_ERP=local to keep working.")

    async def create_po(self, po: ErpPurchaseOrder) -> str:
        raise ErpNotReadyError(self._reason + " Set FINANCE_POD_ERP=local to keep working.")

    async def create_invoice(self, invoice: ErpInvoice) -> str:
        raise ErpNotReadyError(self._reason + " Set FINANCE_POD_ERP=local to keep working.")


def get_erp() -> Erp:
    return WorkdayErp() if get_settings().finance_pod_erp == "workday" else LocalErp()
