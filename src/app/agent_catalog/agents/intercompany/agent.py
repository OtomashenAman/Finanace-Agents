from decimal import ROUND_HALF_UP, Decimal
from typing import Any, cast

from pydantic import BaseModel

from src.app.agent_catalog.agents.base import (
    MAX_SNAPSHOT_LINES,
    Analysis,
    AnalysisContext,
    Autofill,
    BaseAgent,
    Calculation,
    Evidence,
    Finding,
    as_of,
)
from src.app.agent_catalog.agents.checks import (
    ZERO,
    evidence_check,
    has_severity,
    missing,
    money,
    tolerance_check,
)
from src.app.agent_catalog.agents.fields import PolicySettings
from src.app.agent_catalog.agents.intercompany import prompt
from src.app.agent_catalog.agents.intercompany.models import IntercompanyRun
from src.app.agent_catalog.agents.intercompany.schemas import IntercompanyInput
from src.app.agent_catalog.runs.models import FlagSeverity
from src.app.data_sources.access import FinanceData
from src.app.data_sources.records import Bill, Invoice, RecordType

CENT = Decimal("0.01")


def _translated_ap(data: IntercompanyInput) -> Decimal:
    return (data.counterparty_ap * data.translation_rate).quantize(CENT, ROUND_HALF_UP)


class IntercompanyAgent(BaseAgent):
    key = "intercompany"
    code = "06"
    name = "Intercompany Matching, Netting & Settlement"
    short_name = "Intercompany"
    description = "Compare entity-to-entity balances and propose controlled netting."
    primary_user = "Intercompany Analyst"
    reviewer = "Treasury & Tax Reviewer"

    input_schema = IntercompanyInput
    run_model = IntercompanyRun
    reference_field = "sending_entity"
    policy_version = "intercompany/v1"
    controls = (
        "Cross-entity mismatch",
        "FX assumptions",
        "Transfer-pricing review",
        "Settlement authorization",
    )
    narrative_guidance = prompt.GUIDANCE
    prompt_version = prompt.PROMPT_VERSION
    approval_amount_label = "Intercompany AR"

    @classmethod
    async def autofill(
        cls, values: dict[str, Any], data: FinanceData, policy: PolicySettings | None = None
    ) -> Autofill:
        """Each side from its own entity's books (the QuickBooks company linked to it on Data
        Sources): the AR as the sender's open invoices to the receiver, the AP as the
        receiver's open bills from the sender. Never one company's books for the other."""
        result = Autofill()
        sending, receiving = values.get("sending_entity"), values.get("receiving_entity")
        if not sending or not receiving:
            return result
        sides = (
            ("intercompany_ar", sending, receiving, "invoices to"),
            ("counterparty_ap", receiving, sending, "bills from"),
        )
        records: dict[str, Any] = {}
        evidence_source = None
        for field, own, counterparty, what in sides:
            if values.get(field) is not None:
                continue
            found = await data.entity_books(own)
            if found is None:
                result.notes.append(
                    Finding(
                        "ENTITY_BOOKS_NOT_LINKED",
                        FlagSeverity.WARNING,
                        f"No QuickBooks company is linked to {own} on Data Sources: enter the "
                        f"{'AR' if field == 'intercompany_ar' else 'AP'} from its books",
                        field,
                    )
                )
                continue
            books, source = found
            # The counterparty may be named by its code or its name in these books
            rows: dict[str, Invoice | Bill] = {}
            for name in await data.entity_aliases(counterparty):
                found_rows: list[Invoice] | list[Bill] = (
                    await books.records(Invoice, RecordType.INVOICE, counterparty=name)
                    if field == "intercompany_ar"
                    else await books.records(Bill, RecordType.BILL, counterparty=name)
                )
                rows.update((r.external_id, r) for r in found_rows)
            open_rows = [r for r in rows.values() if r.open_amount > ZERO]
            if not open_rows:
                result.notes.append(
                    Finding(
                        "NO_INTERCOMPANY_BALANCE",
                        FlagSeverity.WARNING,
                        f"No open {what} '{counterparty}' in {source.name}: check how the "
                        "counterparty is named in its books",
                        field,
                    )
                )
                continue
            total = sum((r.open_amount for r in open_rows), ZERO)
            result.values[field] = total
            result.sources[field] = f"{source.name}: open {what} {counterparty}"
            records[f"{own} {what} {counterparty}"] = [
                r.model_dump(mode="json") for r in open_rows[:MAX_SNAPSHOT_LINES]
            ]
            evidence_source = evidence_source or source
            numbers = ", ".join(r.doc_number for r in open_rows[:5])
            more = f" and {len(open_rows) - 5} more" if len(open_rows) > 5 else ""
            result.notes.append(
                Finding(
                    "FILLED_FROM_DATA",
                    FlagSeverity.INFO,
                    f"{'Intercompany AR' if field == 'intercompany_ar' else 'Counterparty AP'} "
                    f"{money(total)}: {len(open_rows)} open {what} {counterparty} in "
                    f"{source.name} ({numbers}{more}){as_of(source)}",
                    field,
                )
            )
        if evidence_source is not None:
            result.evidence = Evidence(
                evidence_source, "data", f"{sending} / {receiving} intercompany", records
            )
        return result

    @classmethod
    def approval_amount(cls, data: BaseModel) -> Decimal | None:
        return cast(IntercompanyInput, data).intercompany_ar

    @classmethod
    async def analyze(cls, data: BaseModel, ctx: AnalysisContext) -> Analysis:
        ic = cast(IntercompanyInput, data)
        translated = _translated_ap(ic)
        difference = ic.intercompany_ar - translated
        nettable = min(ic.intercompany_ar, translated)
        findings: list[Finding] = []

        if ic.sending_entity.lower() == ic.receiving_entity.lower():
            findings.append(
                Finding(
                    "SAME_ENTITY",
                    FlagSeverity.HIGH,
                    "Sending and receiving entity are the same: not an intercompany balance",
                    "receiving_entity",
                )
            )
        findings.append(
            tolerance_check(
                difference,
                ic.matching_tolerance,
                subject="Intercompany AR",
                other="the translated counterparty AP",
                tolerance_name="matching",
                match_code="IC_MATCH",
                mismatch_code="IC_MISMATCH",
                field="counterparty_ap",
            )
        )
        if ic.translation_rate == 1:
            findings.append(
                Finding(
                    "NO_TRANSLATION",
                    FlagSeverity.PASS,
                    "No currency translation (rate 1)",
                    "translation_rate",
                )
            )
        else:
            findings.append(
                Finding(
                    "FX_ASSUMPTION",
                    FlagSeverity.WARNING,
                    f"Translation rate {ic.translation_rate.normalize():f} applied: confirm its "
                    "source and date",
                    "translation_rate",
                )
            )
        optional_checks = [
            missing(
                ic.transfer_pricing_notes,
                code="TRANSFER_PRICING_REVIEW",
                message="No transfer-pricing or policy notes: the charges need a tax review",
                field="transfer_pricing_notes",
            ),
            evidence_check(ctx, "intercompany statements or agreement"),
        ]
        findings.extend(f for f in optional_checks if f is not None)
        findings.append(
            Finding(
                "SETTLEMENT_AUTHORIZATION",
                FlagSeverity.INFO,
                "Any netting or settlement needs treasury and tax authorization",
            )
        )

        mismatch = any(f.code == "IC_MISMATCH" for f in findings)
        exceptions = has_severity(findings, FlagSeverity.HIGH)
        if mismatch:
            headline = "Intercompany mismatch"
        elif exceptions:
            headline = "Intercompany exception"
        elif has_severity(findings, FlagSeverity.WARNING):
            headline = "Intercompany match needs review"
        else:
            headline = "Intercompany balances match"

        return Analysis(
            headline=headline,
            proposed_decision=(
                "Resolve before settlement" if exceptions else "Netting proposal for authorization"
            ),
            calculations=[
                Calculation("intercompany_ar", "Intercompany AR", ic.intercompany_ar),
                Calculation("counterparty_ap", "Counterparty AP", ic.counterparty_ap),
                Calculation(
                    "translation_rate",
                    "Translation rate",
                    f"{ic.translation_rate.normalize():f}",
                    "number",
                ),
                Calculation("translated_ap", "Counterparty AP (translated)", translated),
                Calculation("difference", "AR - translated AP", difference),
                Calculation("matching_tolerance", "Matching tolerance", ic.matching_tolerance),
                Calculation("nettable_amount", "Amount available to net", nettable),
            ],
            findings=findings,
            computed={
                "translated_ap": translated,
                "difference": difference,
                "nettable_amount": nettable,
            },
        )
