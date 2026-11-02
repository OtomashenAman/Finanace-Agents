"""The onboarding agent (L4 1.5.1): sends the vendor a secure portal link, reads what the
vendor uploads there, and validates the tax ID and screens for sanctions."""

from __future__ import annotations

import difflib
import uuid
from datetime import datetime, timedelta
from typing import TYPE_CHECKING

from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import undefer

from src.app.auth.security import create_purpose_token
from src.app.common.clock import utcnow
from src.app.common.text_extraction.base import ExtractionError
from src.app.common.text_extraction.registry import extract_text
from src.app.core.config import get_settings
from src.app.data_sources import crypto
from src.app.finance_pod import sanctions
from src.app.finance_pod.common import draft_once, is_sent, need, policy_of
from src.app.finance_pod.flows.ap_vendor_onboarding import reading
from src.app.finance_pod.flows.ap_vendor_onboarding.policy import VndPolicy
from src.app.finance_pod.flows.ap_vendor_onboarding.results import (
    BankRead,
    DocumentsRead,
    Invitation,
    SanctionsHit,
    TaxRead,
    Validation,
)
from src.app.service_pod.core.cases.models import PodReviewTask, ReviewTaskKind
from src.app.service_pod.core.messaging.models import (
    ArtifactChannel,
    ArtifactKind,
    Audience,
    MessageStatus,
    PodArtifact,
    PodMessage,
)
from src.app.service_pod.core.steps.spec import StepFailedError, StepSpec

if TYPE_CHECKING:
    from src.app.service_pod.core.cases.service import Ctx

Results = dict[str, BaseModel]
PORTAL = "vendor_portal"
INVITE = "vendor_invite"


def portal_link(token: str) -> str:
    return f"{get_settings().public_base_url.rstrip('/')}/vendor/{token}"


def issue_link(c: Ctx) -> tuple[str, datetime]:
    """A new signed link for this case (the previous one stops working)."""
    days = policy_of(c.case, VndPolicy).portal_link_days
    jti = uuid.uuid4().hex
    expires = utcnow() + timedelta(days=days)
    token = create_purpose_token(PORTAL, {"case": str(c.case.id), "jti": jti}, timedelta(days=days))
    c.case.state = {**c.case.state, "portal": {"jti": jti, "expires_at": expires.isoformat()}}
    return token, expires


async def send_invitation(c: Ctx, step: StepSpec) -> Results:
    """1.5.1.a: the link goes to the contact the buyer named (a typed address: the vendor
    isn't in the master yet), with no figures; a person sends it."""
    name = c.case.selection["vendor_name"]
    email = c.case.selection["contact_email"]
    portal = c.case.state.get("portal")
    expires = datetime.fromisoformat(portal["expires_at"]) if portal else None
    message = await c.session.scalar(
        select(PodMessage)
        .where(
            PodMessage.case_id == c.case.id,
            PodMessage.purpose == INVITE,
            PodMessage.status != MessageStatus.SEND_FAILED,
        )
        .order_by(PodMessage.created_at.desc())
    )
    if message is None or expires is None or expires <= utcnow():
        token, expires = issue_link(c)
        message = await draft_once(
            c, purpose=INVITE, audience=Audience.INVITE, to_email=email, to_name=name,
            subject="Set up as a supplier: please upload your documents",
            body=(f"Hello,\n\nTo set {name} up as a supplier, please upload these documents "
                  f"through our secure page:\n\n{portal_link(token)}\n\n- Tax form (W-9, or "
                  "W-8BEN / W-8BEN-E outside the US)\n- A letter from your bank confirming the "
                  "account, on the bank's letterhead\n- Insurance or compliance papers, if any"
                  f"\n\nThe link works until {expires:%d %b %Y}. We never ask for bank details "
                  "by email: please don't send them that way.\n\nThank you."),
        )  # fmt: skip
    if not is_sent(message):
        raise StepFailedError(
            f"The portal invitation to {email} is drafted: review and send it, then run this "
            "step again."
        )
    return {"1.5.1.a": Invitation(message_id=message.id, to_email=email, link_expires_at=expires)}


async def _portal_documents(c: Ctx, kind: ArtifactKind) -> list[PodArtifact]:
    return list(
        await c.session.scalars(
            select(PodArtifact)
            .options(undefer(PodArtifact.content))
            .where(
                PodArtifact.case_id == c.case.id,
                PodArtifact.kind == kind,
                PodArtifact.channel == ArtifactChannel.VENDOR_PORTAL,
            )
            .order_by(PodArtifact.created_at.desc())
        )
    )


def _text(doc: PodArtifact) -> str:
    try:
        return extract_text(doc.content, doc.filename).text
    except ExtractionError:
        return ""


async def read_documents(c: Ctx, step: StepSpec) -> Results:
    """1.5.1.b: only documents the vendor uploaded through the portal count (AP1.G2)."""
    tax_docs = await _portal_documents(c, ArtifactKind.TAX_FORM)
    bank_docs = await _portal_documents(c, ArtifactKind.BANK_LETTER)
    if not tax_docs or not bank_docs:
        waiting = [n for n, d in (("tax form", tax_docs), ("bank letter", bank_docs)) if not d]
        raise StepFailedError(f"Waiting for the vendor to upload: {', '.join(waiting)}.")
    tax_doc, bank_doc = tax_docs[0], bank_docs[0]
    manual = c.case.state.get("manual_read")
    tax = reading.read_tax_form(_text(tax_doc))
    bank = reading.read_bank_letter(_text(bank_doc))
    read_by = "text"
    if (tax is None or bank is None) and manual:
        if manual["tax_document_id"] != str(tax_doc.id) or manual["bank_document_id"] != str(
            bank_doc.id
        ):
            raise StepFailedError("The manual reading is for older documents: read the new ones.")
        tax = reading.TaxDetails(
            form=manual["tax_form"], legal_name=manual["legal_name"], tax_id=manual.get("tax_id"),
            tax_id_type="EIN" if manual.get("tax_id") else "foreign",
        )  # fmt: skip
        bank = reading.BankDetails(
            bank_name=manual["bank_name"], account_holder=manual["account_holder"],
            account_number=manual["account_number"], routing_number=manual.get("routing_number"),
            iban=manual.get("iban"),
        )  # fmt: skip
        read_by = "manual"
    if tax is None or bank is None:
        unread = [n for n, v in (("tax form", tax), ("bank letter", bank)) if v is None]
        raise StepFailedError(
            f"Couldn't read the {' and '.join(unread)} (a scanned document has no text and "
            "there's no OCR yet): an AP analyst enters what it says (Enter details by hand)."
        )
    # The full numbers stay encrypted in the case; results carry masked forms and a digest
    c.case.state = {
        **c.case.state,
        "_secure": crypto.encrypt_json(
            {"tax_id": tax.tax_id, "account_number": bank.account_number,
             "routing_number": bank.routing_number, "iban": bank.iban}
        ),
    }  # fmt: skip
    compliance = await _portal_documents(c, ArtifactKind.COMPLIANCE)
    return {
        "1.5.1.b": DocumentsRead(
            tax=TaxRead(
                form=tax.form, legal_name=tax.legal_name, tax_id_type=tax.tax_id_type,
                tax_id_masked=reading.mask(tax.tax_id), document_id=tax_doc.id, read_by=read_by,
            ),
            bank=BankRead(
                bank_name=bank.bank_name, account_holder=bank.account_holder,
                account_masked=reading.mask(bank.account_number) or "",
                routing_masked=reading.mask(bank.routing_number),
                iban_masked=reading.mask(bank.iban), fingerprint=bank.fingerprint(),
                document_id=bank_doc.id, read_by=read_by,
            ),
            compliance_documents=[d.id for d in compliance],
        )
    }  # fmt: skip


def secure(c: Ctx) -> dict[str, str | None]:
    blob = c.case.state.get("_secure")
    if not blob:
        raise StepFailedError("The documents haven't been read yet.")
    values: dict[str, str | None] = crypto.decrypt_json(blob)
    return values


async def validate(c: Ctx, step: StepSpec) -> Results:
    """1.5.1.c: the tax ID's form and the name on it, and the OFAC SDN screening."""
    docs = need(c, "1.5.1.b", DocumentsRead)
    numbers = secure(c)
    policy = policy_of(c.case, VndPolicy)
    tax = reading.TaxDetails(
        form=docs.tax.form, legal_name=docs.tax.legal_name, tax_id=numbers.get("tax_id"),
        tax_id_type=docs.tax.tax_id_type,
    )  # fmt: skip
    checks = reading.check_tax_id(tax)
    routing = numbers.get("routing_number")
    if routing and not reading.aba_valid(routing):
        checks.append("the bank routing number fails its checksum")
    vendor = c.case.selection["vendor_name"]
    name_ok = (
        bool(docs.tax.legal_name)
        and difflib.SequenceMatcher(
            None, sanctions.normalize(vendor), sanctions.normalize(docs.tax.legal_name or "")
        ).ratio()
        >= 0.8
    )
    if not name_ok:
        checks.append(f"the name on the tax form ({docs.tax.legal_name}) differs from {vendor}")
    loaded = await sanctions.current(c.session)
    if loaded is None:
        raise StepFailedError(
            "The OFAC sanctions list isn't loaded yet (daily job, or Admin → Finance POD): "
            "a vendor is never passed unscreened."
        )
    names = [vendor, docs.tax.legal_name or "", docs.bank.account_holder or ""]
    hits = await sanctions.screen(c.session, names, policy.sanctions_match_threshold)
    if hits and not any(t.subject == "Sanctions screening" for t in c.children.review_tasks):
        task = PodReviewTask(
            case_id=c.case.id, kind=ReviewTaskKind.OTHER, subject="Sanctions screening",
            detail="Possible OFAC SDN match: " + "; ".join(
                f"{h.screened_name} ~ {h.listed_name} (entry {h.entry_id}, {h.programs or 'n/a'},"
                f" score {h.score})" for h in hits
            ) + ". Clear it with the evidence, or stop the onboarding.",
            blocking=True, created_by=None,
        )  # fmt: skip
        c.session.add(task)
        c.children.review_tasks.append(task)
    if checks:
        raise StepFailedError("Validation failed: " + "; ".join(checks) + ".")
    return {
        "1.5.1.c": Validation(
            tax_id_valid=True, tax_id_checks=["format", "IRS prefix", "name on the form"],
            name_matches=name_ok, sanctions_list=f"{loaded.list_name} ({loaded.entries} entries)",
            sanctions_loaded_at=loaded.created_at, screened=[n for n in names if n],
            hits=[SanctionsHit(**h.__dict__) for h in hits],
            not_checked="IRS TIN matching (needs GIA's IRS e-Services registration)",
        )
    }  # fmt: skip
