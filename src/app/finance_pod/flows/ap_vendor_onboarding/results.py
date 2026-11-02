"""What each L5 step of a vendor onboarding records. Bank and tax numbers are never stored
in a result: only masked forms and a digest (the full values are encrypted in the case)."""

import uuid
from datetime import datetime
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator


class _Result(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Invitation(_Result):
    """1.5.1.a Sends secure portal link."""

    message_id: uuid.UUID
    to_email: str
    link_expires_at: datetime


class TaxRead(_Result):
    form: Literal["W-9", "W-8BEN", "W-8BEN-E", "unknown"]
    legal_name: str | None
    tax_id_type: Literal["EIN", "SSN", "ITIN", "foreign", "none"]
    tax_id_masked: str | None  # e.g. "**-***4567"
    document_id: uuid.UUID
    read_by: Literal["text", "manual"]


class BankRead(_Result):
    bank_name: str | None
    account_holder: str | None
    account_masked: str  # "****6789"
    routing_masked: str | None
    iban_masked: str | None
    fingerprint: str  # digest of the full details: a change shows as a new digest
    document_id: uuid.UUID
    read_by: Literal["text", "manual"]


class DocumentsRead(_Result):
    """1.5.1.b Reads tax form and bank letter."""

    tax: TaxRead
    bank: BankRead
    compliance_documents: list[uuid.UUID]


class SanctionsHit(_Result):
    screened_name: str
    listed_name: str
    entry_id: str
    programs: str | None
    score: float


class Validation(_Result):
    """1.5.1.c Validates tax ID; sanctions screen."""

    tax_id_valid: bool
    tax_id_checks: list[str]
    name_matches: bool
    sanctions_list: str  # which list and load it used
    sanctions_loaded_at: datetime
    screened: list[str]
    hits: list[SanctionsHit]  # each one is a blocking review task until cleared
    not_checked: str  # what this screening can't do (stated, never implied)


class CallBack(_Result):
    """1.5.2.a Calls back to confirm bank."""

    phone_number: str = Field(min_length=6, max_length=40, title="Number called")
    number_source: Literal[
        "vendor master before this request", "public directory", "earlier correspondence"
    ] = Field(title="Where the number came from (never the bank letter or the email)")
    spoke_with: str = Field(min_length=2, max_length=140, title="Who confirmed")
    called_at: datetime = Field(title="When")
    account_last4: str = Field(pattern=r"^\d{4}$", title="Last 4 digits they confirmed")
    confirmed: Literal[True] = Field(title="The vendor confirmed the bank details")


class Activation(_Result):
    """1.5.2.b Second approver activates vendor."""

    approved: Literal[True] = Field(title="Activate this vendor")
    note: str | None = Field(default=None, max_length=2000, title="Note")


class ManualDetails(BaseModel):
    """An AP analyst reads a scanned document by hand (no OCR yet)."""

    tax_document_id: uuid.UUID
    bank_document_id: uuid.UUID
    legal_name: str = Field(min_length=2, max_length=140)
    tax_form: Literal["W-9", "W-8BEN", "W-8BEN-E"]
    tax_id: str | None = Field(default=None, max_length=20)
    bank_name: str = Field(min_length=2, max_length=140)
    account_holder: str = Field(min_length=2, max_length=140)
    account_number: str = Field(pattern=r"^[0-9]{4,17}$")
    routing_number: str | None = Field(default=None, pattern=r"^[0-9]{9}$")
    iban: str | None = Field(default=None, pattern=r"^[A-Z]{2}[0-9]{2}[A-Z0-9]{10,30}$")

    @model_validator(mode="after")
    def _w9_has_tin(self) -> Self:
        if self.tax_form == "W-9" and not self.tax_id:
            raise ValueError("A W-9 carries a US tax ID: enter it.")
        return self
