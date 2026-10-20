"""Canonical finance records. Every source (QuickBooks sync, file upload) is normalized into
these shapes, so agents read the same data whichever system it came from."""

from datetime import date
from decimal import Decimal
from enum import StrEnum
from typing import Annotated

from pydantic import AfterValidator, BaseModel, BeforeValidator, ConfigDict, Field

CENT = Decimal("0.01")

# Amounts are kept to the cent. JSON floats (QuickBooks sends 12500.0) go through str() so
# no binary noise gets in; more than two decimals is an error, never silently rounded
Money = Annotated[
    Decimal,
    BeforeValidator(lambda v: Decimal(str(v)) if isinstance(v, float) else v),
    Field(max_digits=18, decimal_places=2),
    AfterValidator(lambda v: v.quantize(CENT)),
]


class RecordType(StrEnum):
    VENDOR = "vendor"
    BILL = "bill"
    PURCHASE_ORDER = "purchase_order"
    ACCOUNT = "account"


class Record(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="ignore")

    external_id: str = Field(min_length=1, max_length=100)

    # Columns copied to finance_records for lookups; subclasses map them to their own fields
    @property
    def reference(self) -> str:
        raise NotImplementedError

    @property
    def counterparty(self) -> str | None:
        return None

    @property
    def amount(self) -> Decimal | None:
        return None

    @property
    def txn_date(self) -> date | None:
        return None


class Vendor(Record):
    name: str = Field(min_length=1, max_length=200)
    email: str | None = Field(default=None, max_length=320)
    tax_id: str | None = Field(default=None, max_length=50)
    active: bool = True

    @property
    def reference(self) -> str:
        return self.name


class Bill(Record):
    """A supplier invoice."""

    doc_number: str = Field(min_length=1, max_length=100)
    vendor_name: str = Field(min_length=1, max_length=200)
    total: Money
    tax_total: Money | None = None
    bill_date: date | None = None
    due_date: date | None = None
    po_number: str | None = Field(default=None, max_length=100)
    account: str | None = Field(default=None, max_length=100)

    @property
    def reference(self) -> str:
        return self.doc_number

    @property
    def counterparty(self) -> str | None:
        return self.vendor_name

    @property
    def amount(self) -> Decimal | None:
        return self.total

    @property
    def txn_date(self) -> date | None:
        return self.bill_date


class PurchaseOrder(Record):
    po_number: str = Field(min_length=1, max_length=100)
    vendor_name: str = Field(min_length=1, max_length=200)
    total: Money
    received_amount: Money | None = None
    status: str | None = Field(default=None, max_length=50)
    po_date: date | None = None

    @property
    def reference(self) -> str:
        return self.po_number

    @property
    def counterparty(self) -> str | None:
        return self.vendor_name

    @property
    def amount(self) -> Decimal | None:
        return self.total

    @property
    def txn_date(self) -> date | None:
        return self.po_date


class Account(Record):
    """A GL account from the chart of accounts."""

    number: str | None = Field(default=None, max_length=50)
    name: str = Field(min_length=1, max_length=200)
    account_type: str | None = Field(default=None, max_length=100)

    @property
    def reference(self) -> str:
        return self.number or self.name


RECORD_MODELS: dict[RecordType, type[Record]] = {
    RecordType.VENDOR: Vendor,
    RecordType.BILL: Bill,
    RecordType.PURCHASE_ORDER: PurchaseOrder,
    RecordType.ACCOUNT: Account,
}

RECORD_LABELS: dict[RecordType, str] = {
    RecordType.VENDOR: "Vendors",
    RecordType.BILL: "Bills (supplier invoices)",
    RecordType.PURCHASE_ORDER: "Purchase orders",
    RecordType.ACCOUNT: "Chart of accounts",
}
