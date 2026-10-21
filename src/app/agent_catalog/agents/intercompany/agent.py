from decimal import ROUND_HALF_UP, Decimal
from typing import cast

from pydantic import BaseModel

from src.app.agent_catalog.agents.base import (
    Analysis,
    AnalysisContext,
    BaseAgent,
    Calculation,
    Finding,
)
from src.app.agent_catalog.agents.checks import (
    evidence_check,
    has_severity,
    missing,
    tolerance_check,
)
from src.app.agent_catalog.agents.intercompany import prompt
from src.app.agent_catalog.agents.intercompany.models import IntercompanyRun
from src.app.agent_catalog.agents.intercompany.schemas import IntercompanyInput
from src.app.agent_catalog.runs.models import FlagSeverity

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
