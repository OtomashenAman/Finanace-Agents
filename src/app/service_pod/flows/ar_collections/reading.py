"""Reading a customer's reply into proposed commitments, disputes and document requests,
each tied to the customer's own words. What doesn't pass the checks goes to a person."""

import uuid
from collections import defaultdict
from datetime import date
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.core.llm.base import LLMProvider
from src.app.service_pod.common import ai, reading
from src.app.service_pod.common.canonical import plain
from src.app.service_pod.core.cases import system
from src.app.service_pod.core.cases.models import (
    CommitmentStatus,
    PodCase,
    PodCommitment,
    PodReviewTask,
    ReviewTaskKind,
)
from src.app.service_pod.core.messaging.models import ArtifactKind, PodMessage
from src.app.service_pod.flows.ar_collections.prompt import READ_PROMPT_VERSION, READ_SYSTEM
from src.app.service_pod.flows.ar_collections.schemas import ArReplyRead, ArTranche
from src.app.service_pod.flows.ar_collections.service import invoices_of

MIN_CONFIDENCE = 0.8


def _structural_problems(read: ArReplyRead, reply: str, numbers: set[str]) -> list[str]:
    """Problems that make the whole reading unusable (the reply then goes to a person)."""
    problems = []
    quotes = [t.quote for t in read.tranches] + [d.quote for d in read.disputes]
    quotes += [r.quote for r in read.document_requests]
    for quote in quotes:
        if not reading.quote_in(reply, quote):
            problems.append(f"quote not found in the reply: {quote[:80]!r}")
    for number in (
        [t.invoice_number for t in read.tranches]
        + [d.invoice_number for d in read.disputes]
        + [n for r in read.document_requests for n in r.invoice_numbers]
    ):
        if number not in numbers:
            problems.append(f"{number} isn't an invoice of this case")
    for t in read.tranches:
        if reading.parse_money(t.amount) is None:
            problems.append(f"unreadable amount {t.amount!r}")
    return problems


async def extract_reply(
    session: AsyncSession, case: PodCase, message: PodMessage, llm: LLMProvider
) -> None:
    invoices = invoices_of(case)
    original = (
        await session.get(PodMessage, message.in_reply_to_id) if message.in_reply_to_id else None
    )
    user = (
        f"Reply date: {(message.received_at or message.created_at).date().isoformat()}\n"
        f"Invoices (number, due date, open balance):\n"
        + "\n".join(f"- {n} {r['due_date']} {r['balance']}" for n, r in invoices.items())
        + (f"\n\nOur message:\n{original.body}" if original else "")
        + f"\n\nCustomer reply:\n{message.body}"
    )
    result = await ai.extract(
        llm,
        system=READ_SYSTEM,
        user=user,
        schema=ArReplyRead,
        prompt_version=READ_PROMPT_VERSION,
        validate=lambda r: _structural_problems(r, message.body, set(invoices)),
    )
    read = result.output
    notes = await _apply(session, case, message, read, invoices)
    message.extraction = plain(
        {"output": read, "provenance": result.provenance.as_dict(), "notes": notes}
    )


async def _apply(
    session: AsyncSession,
    case: PodCase,
    message: PodMessage,
    read: ArReplyRead,
    invoices: dict[str, dict[str, object]],
) -> list[str]:
    notes: list[str] = []
    commitments = list(
        await session.scalars(select(PodCommitment).where(PodCommitment.case_id == case.id))
    )
    tasks = await system.open_tasks(session, case)
    committed: dict[str, Decimal] = defaultdict(Decimal)
    for x in commitments:
        if x.status != CommitmentStatus.REJECTED:
            committed[x.invoice_number] += x.amount
    disputed: dict[str, Decimal] = defaultdict(Decimal)
    for d in read.disputes:
        disputed[d.invoice_number] += reading.parse_money(d.amount or "") or Decimal(0)

    for t in read.tranches:
        number, amount = t.invoice_number, reading.parse_money(t.amount)
        assert amount is not None  # noqa: S101 - structural check
        balance = reading.dec(invoices[number]["balance"])
        problems = []
        if t.confidence < MIN_CONFIDENCE:
            problems.append("the reading is uncertain")
        if reading.conditional(t.quote):
            problems.append("the promise is conditional")
        if not reading.amount_supported(t.quote, amount) and not (t.inferred and amount == balance):
            problems.append("the amount isn't in the customer's words")
        when = reading.parse_date(t.date)
        if when is not None and not reading.date_supported(t.quote, when):
            notes.append(f"{number}: {when} isn't in the customer's words, treated as no date")
            when = None
        # A date for a promise already on the case (e.g. "the $6k on Nov 8"): not a new promise
        undated = next(
            (
                x
                for x in commitments
                if x.invoice_number == number
                and x.amount == amount
                and x.expected_date is None
                and x.status == CommitmentStatus.PROPOSED
            ),
            None,
        )
        if undated is None and committed[number] + amount + disputed[number] > balance:
            problems.append("it would exceed the open balance with what is already promised")
        if problems:
            system.raise_task(
                session,
                case,
                ReviewTaskKind.AMBIGUITY,
                f'"{t.quote}": {", ".join(problems)}. Clarify with the customer or record it '
                "by hand.",
                subject=number,
            )
            continue
        if undated is not None:
            if when is not None:
                _date_from_customer(undated, when, t.quote, message, tasks)
                notes.append(f"{number}: the customer dated the {amount} payment {when}")
            continue
        _new_commitment(session, case, message, number, invoices, amount, when, t, notes)
        committed[number] += amount

    for d in read.disputes:
        system.raise_task(
            session,
            case,
            ReviewTaskKind.DISPUTE,
            f'{d.amount or "Part"} disputed: {d.reason} ("{d.quote}")',
            subject=d.invoice_number,
        )
    for r in read.document_requests:
        kind = r.kind if r.kind in {k.value for k in ArtifactKind} else ArtifactKind.OTHER.value
        targets: list[str | None] = [*r.invoice_numbers] or [None]
        for target in targets:
            system.raise_task(
                session,
                case,
                ReviewTaskKind.MISSING_DOCUMENT,
                f'The customer asks for {kind.replace("_", " ")}: "{r.quote}"',
                subject=target,
                requirement={"type": "document", "kind": kind, "invoice": target},
            )
    for item in read.unclear:
        system.raise_task(session, case, ReviewTaskKind.AMBIGUITY, item[:2000], blocking=True)
    return notes


def _new_commitment(
    session: AsyncSession,
    case: PodCase,
    message: PodMessage,
    number: str,
    invoices: dict[str, dict[str, object]],
    amount: Decimal,
    when: date | None,
    t: ArTranche,
    notes: list[str],
) -> None:
    commitment = PodCommitment(
        id=uuid.uuid4(),
        case_id=case.id,
        invoice_id=str(invoices[number]["id"]),
        invoice_number=number,
        amount=amount,
        expected_date=when,
        probability=Decimal(1),
        quote=t.quote,
        source_message_id=message.id,
        created_by=None,
    )
    session.add(commitment)
    if when is None:
        system.raise_task(
            session,
            case,
            ReviewTaskKind.UNKNOWN_DATE,
            f'No date for {amount} on {number}: "{t.quote}". Ask the customer for it.',
            subject=number,
            requirement={"type": "customer_date", "commitment_id": str(commitment.id)},
        )
    notes.append(f"{number}: proposed {amount} " + (f"on {when}" if when else "without a date"))


def _date_from_customer(
    commitment: PodCommitment,
    when: date,
    quote: str,
    message: PodMessage,
    tasks: list[PodReviewTask],
) -> None:
    commitment.expected_date = when
    commitment.quote = f"{commitment.quote} / {quote}" if commitment.quote else quote
    commitment.source_message_id = message.id
    for task in tasks:
        req = task.requirement or {}
        if req.get("type") == "customer_date" and req.get("commitment_id") == str(commitment.id):
            system.resolve(task, f'The customer gave {when.isoformat()}: "{quote}"')
