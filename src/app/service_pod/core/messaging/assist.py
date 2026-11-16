"""Help writing a case's email: the AI drafts or changes it from a plain-English request
("make it firmer", "mention the MSA", "write a first reminder"), and the result can be saved
as the customer's own template.

The verified invoice table stays exactly as the source gives it: the AI sees a placeholder
line instead and must keep it, and may not add figures that aren't already in the request,
the draft or the table.
"""

import re
import uuid

from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.audit.service import record_event
from src.app.common.context import RequestContext
from src.app.core.config import get_settings
from src.app.core.errors import AppError
from src.app.core.llm.base import LLMError, LLMProvider
from src.app.service_pod.common import ai
from src.app.service_pod.common.people import name_of, names
from src.app.service_pod.core.access.service import PodAccess
from src.app.service_pod.core.cases.access import load_case
from src.app.service_pod.core.cases.models import PodCase
from src.app.service_pod.core.messaging import templates
from src.app.service_pod.core.messaging.models import PodEmailTemplate
from src.app.service_pod.core.messaging.schemas import (
    AssistOut,
    AssistRequest,
    TemplateIn,
    TemplateOut,
)
from src.app.service_pod.core.messaging.service import (
    MessageRefusedError,
    _facts_for,
    _require_open,
)

ASSIST_PROMPT_VERSION = "pod_email_assist/v1"
TABLE = "[INVOICE TABLE]"
_FIGURE = re.compile(r"\d+(?:[.,]\d+)*")


class AiUnavailableError(AppError):
    status_code = 503
    code = "ai_unavailable"


class NoCustomerTemplateError(AppError):
    status_code = 409
    code = "no_customer_template"
    message = "Templates are saved per customer: this case isn't about one customer."


class _Draft(BaseModel):
    subject: str = Field(description="The email subject line")
    body: str = Field(description=f"The email body, plain text, with {TABLE} on its own line")


def _normalize(text: str) -> str:
    return "\n".join(line.rstrip() for line in text.replace("\r\n", "\n").split("\n")).strip()


def _figures(text: str) -> set[str]:
    return {f.replace(",", "") for f in _FIGURE.findall(text)}


def _problems(draft: _Draft, fact_block: str | None, known: set[str]) -> list[str]:
    problems = []
    if not draft.subject.strip() or not draft.body.strip():
        problems.append("the subject or body is empty")
    if fact_block is not None and draft.body.count(TABLE) != 1:
        problems.append("the invoice table placeholder must appear exactly once")
    added = _figures(draft.subject + "\n" + draft.body.replace(TABLE, "")) - known
    if added:
        problems.append(
            f"it added figures ({', '.join(sorted(added)[:5])}) that aren't in your request, "
            "the draft or the invoice table"
        )
    return problems


async def assist(
    session: AsyncSession, case_id: uuid.UUID, body: AssistRequest, llm: LLMProvider
) -> AssistOut:
    case = await load_case(session, case_id)
    _require_open(case)
    fact_block = await _facts_for(session, case, body.purpose, body.invoice_numbers)
    current = _normalize(body.body)
    if fact_block:
        block = _normalize(fact_block)
        current = current.replace(block, TABLE) if block in current else current
    customer = case.state.get("customer") or {}
    signature = get_settings().email_sender_name
    user = (
        f"Request: {body.instruction}\n"
        f"Recipient: {customer.get('contact_name') or customer.get('name') or 'the customer'}\n"
        f"Sign as: {signature}\n\n"
        f"Current subject: {body.subject or '(none)'}\n"
        f"Current body:\n{current or '(empty: write a new email)'}"
    )
    known = _figures(body.instruction + body.subject + body.body + (fact_block or ""))
    try:
        result = await ai.extract(
            llm,
            system=(
                "You write and edit short, professional collection emails for a finance team, "
                "following the user's request (tone, length, what to say). Plain text, no "
                "markdown. "
                + (
                    f"The verified invoice table is shown as the line {TABLE}: keep that line "
                    "exactly once, on its own line, where the table belongs. Never write "
                    "invoice numbers, amounts or dates yourself."
                    if fact_block
                    else "Never invent invoice numbers, amounts or dates."
                )
            ),
            user=user,
            schema=_Draft,
            prompt_version=ASSIST_PROMPT_VERSION,
            validate=lambda d: _problems(d, fact_block, known),
        )
    except LLMError as exc:
        raise AiUnavailableError(
            f"The AI isn't available right now ({str(exc)[:120] or 'not configured'})."
        ) from exc
    except ai.AiOutputRejectedError as exc:
        raise MessageRefusedError(
            f"The AI's draft wasn't used: {exc.message.split(': ', 1)[-1]}. Try again or "
            "rephrase the request."
        ) from exc
    out = result.output
    text = out.body.replace("\\r\\n", "\n").replace("\\n", "\n").strip()
    return AssistOut(
        subject=out.subject.strip()[:300],
        body=text.replace(TABLE, fact_block) if fact_block else text,
    )


# --- the customer's template ---------------------------------------------------------


async def _key(session: AsyncSession, case: PodCase) -> templates.CustomerKey:
    key = await templates.key_of(session, case)
    if key is None:
        raise NoCustomerTemplateError
    return key


async def _out(session: AsyncSession, t: PodEmailTemplate) -> TemplateOut:
    return TemplateOut(
        customer_name=t.customer_name,
        subject=t.subject,
        body=t.body,
        updated_by=name_of(await names(session, [t.updated_by]), t.updated_by),
        updated_at=t.updated_at,
    )


async def get_template(session: AsyncSession, case_id: uuid.UUID) -> TemplateOut | None:
    case = await load_case(session, case_id)
    key = await templates.key_of(session, case)
    saved = await templates.find(session, key) if key else None
    return await _out(session, saved) if saved else None


async def save_template(
    session: AsyncSession,
    access: PodAccess,
    case_id: uuid.UUID,
    body: TemplateIn,
    ctx: RequestContext,
) -> TemplateOut:
    case = await load_case(session, case_id)
    key = await _key(session, case)
    only = body.invoice_numbers
    fact_block = await _facts_for(session, case, body.purpose, only)
    text = templates.generalize(body.body, case, fact_block, only)
    if fact_block and templates.INVOICES not in text:
        raise MessageRefusedError(
            "Keep the invoice table in the email: the template marks where each case's "
            "verified figures go."
        )
    subject = templates.generalize(body.subject, case, None, only)
    saved = await templates.find(session, key)
    if saved is None:
        saved = PodEmailTemplate(
            workflow=key.workflow, company_id=key.company_id, customer_id=key.customer_id
        )
        session.add(saved)
    saved.customer_name = key.customer_name[:200]
    saved.subject = subject[:300]
    saved.body = text
    saved.updated_by = access.user.id
    record_event(
        session,
        "pod.email_template_saved",
        ctx,
        actor_id=access.user.id,
        run=case.reference,
        customer=key.customer_name,
        summary=f"Saved {key.customer_name}'s email template (from {case.reference})",
    )
    await session.commit()
    await session.refresh(saved)
    return await _out(session, saved)


async def delete_template(
    session: AsyncSession, access: PodAccess, case_id: uuid.UUID, ctx: RequestContext
) -> None:
    case = await load_case(session, case_id)
    key = await _key(session, case)
    saved = await templates.find(session, key)
    if saved is None:
        return
    await session.delete(saved)
    record_event(
        session,
        "pod.email_template_deleted",
        ctx,
        actor_id=access.user.id,
        run=case.reference,
        customer=key.customer_name,
        summary=f"Removed {key.customer_name}'s email template",
    )
    await session.commit()
