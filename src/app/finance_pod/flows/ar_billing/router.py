"""Billing's own endpoints: take in every billable submission (AR3.R1), and the monthly
statements a billing analyst drafts and sends in one batch (AR3.P3)."""

import uuid
from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel, Field
from sqlalchemy import select

from src.app.common.context import RequestContextDep
from src.app.common.schemas import ErrorResponse
from src.app.core.db import SessionDep
from src.app.finance_pod.access import FinanceAccessDep
from src.app.finance_pod.capacities import FinanceCapacity as Cap
from src.app.finance_pod.case_api import CapacityRequiredError
from src.app.finance_pod.flows.ar_billing.results import AccountTerms
from src.app.finance_pod.flows.ar_billing.service import (
    KEY,
    STATEMENT,
    live_cases,
    newest_doc,
    statement_body,
    to_bill,
    today,
    waiting_for_statement,
)
from src.app.service_pod.core.messaging import service as messaging
from src.app.service_pod.core.messaging.models import Audience, MessageStatus, PodMessage
from src.app.service_pod.core.messaging.schemas import ApprovalChecks, MessageDraftIn, MessageSend
from src.app.service_pod.core.snapshots import service as snapshots
from src.app.service_pod.core.steps.models import PodCaseStep

router = APIRouter(prefix="/arb", tags=["finance pod: billing"])
_ERRORS: dict[int | str, dict[str, Any]] = {code: {"model": ErrorResponse} for code in (403, 404)}
MONTH = r"^\d{4}-(0[1-9]|1[0-2])$"


def _billing_analyst(access: Any, entity_id: uuid.UUID | None = None) -> None:
    if not access.holds(Cap.BILLING_ANALYST.value, entity_id):
        raise CapacityRequiredError("Only a billing analyst does this.")


class IntakeRequest(BaseModel):
    snapshot_id: uuid.UUID


class IntakeResult(BaseModel):
    opened: list[str]  # case references
    already: int  # billable submissions that had a case


@router.post("/intake", response_model=IntakeResult, responses=_ERRORS)
async def intake(
    body: IntakeRequest, session: SessionDep, access: FinanceAccessDep, ctx: RequestContextDep
) -> IntakeResult:
    """Open a billing case for every submission whose report is issued and isn't billed."""
    from src.app.service_pod.core.cases.service import open_case

    snapshot = await snapshots.load_snapshot(session, body.snapshot_id)
    _billing_analyst(access, snapshot.entity_id)
    taken = await live_cases(session)
    doc = snapshots.document(snapshot)
    clients = {c.id: c.name for c in doc.clients or []}
    opened = []
    for sub in to_bill(doc, taken):
        case = await open_case(
            session, access, KEY, snapshot,
            f"Bill {clients.get(sub.client_id, sub.client_id)} · {sub.id}",
            {"submission_id": sub.id}, ctx,
        )  # fmt: skip
        opened.append(case.reference)
    await session.commit()
    billable = {s.id for s in doc.submissions or []}
    return IntakeResult(opened=opened, already=len(taken & billable))


class StatementRequest(BaseModel):
    month: str = Field(pattern=MONTH)


class StatementRun(BaseModel):
    drafted: list[str]  # clients
    sent: list[str]
    skipped: list[str]  # why a client got none


@router.post("/statements", response_model=StatementRun, responses=_ERRORS)
async def draft_statements(
    body: StatementRequest, session: SessionDep, access: FinanceAccessDep
) -> StatementRun:
    """Draft the month's statement for every client with an invoice waiting for one: their
    open items as the newest books hold them, on their latest billing case."""
    _billing_analyst(access)
    drafted, skipped = [], []
    for client_id, cases in (await waiting_for_statement(session)).items():
        case = max(cases, key=lambda c: c.created_at)
        terms_row = await session.scalar(
            select(PodCaseStep).where(
                PodCaseStep.case_id == case.id, PodCaseStep.l5_code == "3.1.2.b"
            )
        )
        terms = AccountTerms.model_validate(terms_row.result) if terms_row else None
        if terms is None or not terms.email:
            skipped.append(f"{client_id}: no contact email")
            continue
        subject = f"Statement of account {body.month}"
        exists = await session.scalar(
            select(PodMessage.id).where(
                PodMessage.case_id == case.id, PodMessage.purpose == STATEMENT,
                PodMessage.subject == subject, PodMessage.status != MessageStatus.SEND_FAILED,
            )
        )  # fmt: skip
        if exists:
            skipped.append(f"{client_id}: drafted already")
            continue
        doc = await newest_doc(session, case)
        await messaging.add_draft(
            session, case,
            MessageDraftIn(audience=Audience.CUSTOMER, purpose=STATEMENT, to_email=terms.email,
                           to_name=terms.client_name, subject=subject,
                           body=statement_body(doc, client_id, body.month, today())),
            access.user.id,
        )  # fmt: skip
        drafted.append(client_id)
    await session.commit()
    return StatementRun(drafted=drafted, sent=[], skipped=skipped)


@router.post("/statements/send", response_model=StatementRun, responses=_ERRORS)
async def send_statements(
    body: StatementRequest, session: SessionDep, access: FinanceAccessDep, ctx: RequestContextDep
) -> StatementRun:
    """Send every drafted statement of the month in one batch (the click approves each)."""
    _billing_analyst(access)
    drafts = list(
        await session.scalars(
            select(PodMessage).where(
                PodMessage.purpose == STATEMENT,
                PodMessage.subject == f"Statement of account {body.month}",
                PodMessage.status == MessageStatus.DRAFT,
            )
        )
    )
    sent, skipped = [], []
    checks = ApprovalChecks(recipient=True, mapping=True, tone=True)
    for message in drafts:
        try:
            out = await messaging.send_message(
                session, access, message.id,
                MessageSend(expected_version=message.version, checks=checks), ctx,
            )  # fmt: skip
            sent.append(out.to_name or out.to_email)
        except messaging.MessageRefusedError as exc:
            skipped.append(f"{message.to_name or message.to_email}: {exc.message}")
    return StatementRun(drafted=[], sent=sent, skipped=skipped)
