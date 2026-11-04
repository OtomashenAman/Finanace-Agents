"""Reading the customer's reply into allocation lines in their own words; a matching amount
never decides it."""

from decimal import Decimal

from sqlalchemy.ext.asyncio import AsyncSession

from src.app.core.llm.base import LLMProvider
from src.app.service_pod.common import ai, reading
from src.app.service_pod.common.canonical import plain
from src.app.service_pod.core.cases import system
from src.app.service_pod.core.cases.models import PodCase, ReviewTaskKind
from src.app.service_pod.core.messaging.models import ArtifactKind, PodMessage
from src.app.service_pod.flows.bank_recon.prompt import READ_PROMPT_VERSION, READ_SYSTEM
from src.app.service_pod.flows.bank_recon.schemas import BankReplyRead
from src.app.service_pod.flows.bank_recon.service import (
    allocation_problems,
    open_invoices_of,
    receipt_of,
    store_allocation,
)

MIN_CONFIDENCE = 0.8


async def extract_reply(
    session: AsyncSession, case: PodCase, message: PodMessage, llm: LLMProvider
) -> None:
    by_number = {str(r["number"]): r for r in open_invoices_of(case).values()}
    receipt = receipt_of(case)

    def structural(read: BankReplyRead) -> list[str]:
        problems = []
        quotes = [a.quote for a in read.allocations] + [r.quote for r in read.document_requests]
        problems += [
            f"it quoted words that aren't in the reply ({q[:80]!r})"
            for q in quotes
            if not reading.quote_in(message.body, q)
        ]
        numbers = [a.invoice_number for a in read.allocations]
        numbers += [n for r in read.document_requests for n in r.invoice_numbers]
        problems += [
            f"it named invoice {n}, which isn't open for this customer"
            for n in numbers
            if n not in by_number
        ]
        problems += [
            f"it gave an amount it couldn't read ({a.amount!r})"
            for a in read.allocations
            if a.amount.strip() and reading.parse_money(a.amount) is None
        ]
        return problems

    result = await ai.extract(
        llm,
        system=READ_SYSTEM,
        user=(
            f"Payment: {receipt['reference']} {receipt['amount']} {receipt['currency']} on "
            f"{receipt['date']}\nOpen invoices (number, open balance):\n"
            + "\n".join(f"- {n} {r['balance']}" for n, r in by_number.items())
            + f"\n\nCustomer reply:\n{message.body}"
        ),
        schema=BankReplyRead,
        prompt_version=READ_PROMPT_VERSION,
        validate=structural,
    )
    read, notes = result.output, []
    lines: list[tuple[str, Decimal]] = []
    for a in read.allocations:
        amount = reading.parse_money(a.amount)
        if amount is None:  # blank (structural check): the customer stated no amount
            system.raise_task(
                session,
                case,
                ReviewTaskKind.AMBIGUITY,
                f'"{a.quote}": the customer didn\'t say how much goes to {a.invoice_number}. '
                "Clarify with the customer.",
                subject=a.invoice_number,
            )
            continue
        problems = []
        if a.confidence < MIN_CONFIDENCE:
            problems.append("the reading is uncertain")
        if reading.conditional(a.quote):
            problems.append("the instruction is conditional")
        if not reading.amount_supported(a.quote, amount):
            problems.append("the amount isn't in the customer's words")
        if problems:
            system.raise_task(
                session,
                case,
                ReviewTaskKind.AMBIGUITY,
                f'"{a.quote}": {", ".join(problems)}. Clarify with the customer.',
                subject=a.invoice_number,
            )
            continue
        lines.append((str(by_number[a.invoice_number]["id"]), amount))
    if lines and len(lines) == len(read.allocations):
        quote = " / ".join(dict.fromkeys(a.quote for a in read.allocations))
        store_allocation(case, lines, message, quote, "ai")
        problems = allocation_problems(case)
        if problems:
            system.raise_task(
                session,
                case,
                ReviewTaskKind.AMBIGUITY,
                "The customer's allocation doesn't settle the receipt: " + " ".join(problems),
                subject=receipt["reference"],
            )
        notes.append("allocation proposed from the reply")
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
        system.raise_task(session, case, ReviewTaskKind.AMBIGUITY, item[:2000])
    message.extraction = plain(
        {"output": read, "provenance": result.provenance.as_dict(), "notes": notes}
    )
