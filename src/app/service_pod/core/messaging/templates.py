"""A customer's own email format: one saved template per customer of a company (per
workflow), which every new draft to that customer starts from.

The template never holds figures: {{invoices}} is where the case's verified table from the
source goes, and {{invoice_numbers}} becomes the case's invoice numbers.
"""

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.service_pod.core.cases.models import PodCase
from src.app.service_pod.core.messaging.models import PodEmailTemplate
from src.app.service_pod.core.snapshots import service as snapshots
from src.app.service_pod.core.snapshots.models import PodSnapshot

INVOICES = "{{invoices}}"
INVOICE_NUMBERS = "{{invoice_numbers}}"


@dataclass(frozen=True)
class CustomerKey:
    workflow: str
    company_id: str
    customer_id: str
    customer_name: str


async def key_of(session: AsyncSession, case: PodCase) -> CustomerKey | None:
    """Whose template a case uses; None for cases that aren't about one customer."""
    customer = case.state.get("customer")
    if not isinstance(customer, dict) or not customer.get("id"):
        return None
    company_id = case.state.get("company_id")
    if not company_id:  # cases opened before the company was kept: from their snapshot
        snapshot = await session.get(PodSnapshot, case.snapshot_id)
        company_id = snapshots.document(snapshot).company_id if snapshot else None
    if not company_id:
        return None
    return CustomerKey(
        case.workflow, str(company_id), str(customer["id"]), str(customer.get("name") or "")
    )


async def find(session: AsyncSession, key: CustomerKey) -> PodEmailTemplate | None:
    return await session.scalar(
        select(PodEmailTemplate).where(
            PodEmailTemplate.workflow == key.workflow,
            PodEmailTemplate.company_id == key.company_id,
            PodEmailTemplate.customer_id == key.customer_id,
        )
    )


def invoice_numbers(case: PodCase, only: list[str] | None = None) -> str:
    """The numbers the email is about, in the case's order (only: the selected ones)."""
    rows = case.state.get("invoices", [])
    return " / ".join(
        str(r["number"]) for r in rows if only is None or str(r["number"]) in set(only)
    )


def fill(text: str, case: PodCase, fact_block: str | None, only: list[str] | None = None) -> str:
    text = text.replace(INVOICE_NUMBERS, invoice_numbers(case, only))
    return text.replace(INVOICES, fact_block or "")


def generalize(
    text: str, case: PodCase, fact_block: str | None, only: list[str] | None = None
) -> str:
    """A draft of this case turned into the customer's template: its figures and invoice
    numbers become placeholders, filled in again for each new case."""
    if fact_block:
        text = _replace_block(text, fact_block, INVOICES)
    numbers = invoice_numbers(case, only)
    return text.replace(numbers, INVOICE_NUMBERS) if numbers else text


def _normalize(text: str) -> str:
    return "\n".join(line.rstrip() for line in text.replace("\r\n", "\n").split("\n"))


def _replace_block(text: str, block: str, marker: str) -> str:
    text, block = _normalize(text), _normalize(block)
    return text.replace(block, marker, 1)
