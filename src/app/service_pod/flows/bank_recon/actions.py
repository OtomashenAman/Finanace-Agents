"""Bank case actions beyond the engine's: record the allocation by hand, queue the posting."""

from pydantic import BaseModel

from src.app.service_pod.common import reading
from src.app.service_pod.core.cases.exceptions import CaseActionError
from src.app.service_pod.core.cases.models import CaseStatus
from src.app.service_pod.core.cases.schemas import EmptyPayload
from src.app.service_pod.core.cases.service import DRAFT, ActionSpec, Ctx, need_status
from src.app.service_pod.core.messaging.models import Direction, PodMessage
from src.app.service_pod.core.tasks import service as tasks
from src.app.service_pod.core.tasks.models import TaskKind
from src.app.service_pod.core.tasks.schemas import TaskCreate
from src.app.service_pod.flows.bank_recon.schemas import SetAllocationPayload
from src.app.service_pod.flows.bank_recon.service import (
    open_invoices_of,
    receipt_of,
    store_allocation,
)


def _guard_set_allocation(c: Ctx) -> str | None:
    return need_status(c, DRAFT, "change the allocation")


async def _set_allocation(c: Ctx, p: BaseModel) -> tuple[str, bool]:
    assert isinstance(p, SetAllocationPayload)  # noqa: S101
    reply = await c.session.get(PodMessage, p.source_message_id)
    if reply is None or reply.case_id != c.case.id or reply.direction != Direction.INBOUND:
        raise CaseActionError("The allocation must cite a reply imported into this case.")
    if not reading.quote_in(reply.body, p.quote):
        raise CaseActionError("The quote isn't in that reply: copy the customer's words.")
    invoices = open_invoices_of(c.case)
    for line in p.lines:
        if not reading.amount_supported(p.quote, line.amount):
            raise CaseActionError(f"{line.amount} isn't in the quoted words.")
        if line.invoice_id not in invoices:
            raise CaseActionError(f"{line.invoice_id} isn't an open invoice of this customer.")
    store_allocation(
        c.case, [(line.invoice_id, line.amount) for line in p.lines], reply, p.quote, "hand"
    )
    return "Recorded the customer's allocation", True


def _guard_create_task(c: Ctx) -> str | None:
    # A second request for the same receipt is refused by the task's unique key
    return need_status(c, frozenset({CaseStatus.APPROVED}), "queue the posting")


async def _create_task(c: Ctx, _: BaseModel) -> tuple[str, bool]:
    receipt = receipt_of(c.case)
    allocation = c.case.state["allocation"]
    invoices = open_invoices_of(c.case)
    task = await tasks.add_task(
        c.session,
        c.case,
        TaskCreate(
            kind=TaskKind.RECEIVE_PAYMENT,
            reference=receipt["reference"],
            instructions={
                "customer": c.case.state["customer"]["name"],
                "date": receipt["date"],
                "amount": receipt["amount"],
                "currency": receipt["currency"],
                "bank_reference": receipt["reference"],
                "apply_to": allocation["lines"],
                "balances_after": {
                    line["invoice_number"]: str(
                        reading.dec(invoices[line["invoice_id"]]["balance"])
                        - reading.dec(line["amount"])
                    )
                    for line in allocation["lines"]
                },
            },
            note="Receive Payment in QuickBooks, applied exactly as listed.",
        ),
        c.user.id,
    )
    return f"Queued manual Receive Payment {task.reference} for the Finance Admin", False


ACTIONS = {
    "set_allocation": ActionSpec(SetAllocationPayload, _guard_set_allocation, _set_allocation),
    "create_posting_task": ActionSpec(EmptyPayload, _guard_create_task, _create_task),
}
