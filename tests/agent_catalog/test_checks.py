"""The shared building blocks agents are made of: form field helpers and engine checks."""

from decimal import Decimal

import pytest
from pydantic import ValidationError

from src.app.agent_catalog.agents.checks import (
    missing,
    money,
    over_limit,
    percent,
    tolerance_check,
)
from src.app.agent_catalog.agents.fields import (
    AgentInput,
    PolicySettings,
    bool_field,
    draft_schema,
    form_fields,
    number_field,
    number_setting,
    percent_field,
    percent_setting,
    signed_money_field,
    textarea_field,
)
from src.app.agent_catalog.runs.models import FlagSeverity


class SampleInput(AgentInput):
    days_overdue: int = number_field("Days overdue")
    discount_rate: Decimal = percent_field("Annual discount rate")
    gl_balance: Decimal = signed_money_field("GL balance")
    open_dispute: bool = bool_field("Open dispute")
    notes: str | None = textarea_field("Collection notes")


class SamplePolicy(PolicySettings):
    variance_pct: Decimal | None = percent_setting("Variance threshold", Decimal("10"))
    overdue_days: int | None = number_setting("Overdue after", 30)


def test_field_helpers_drive_the_form_spec() -> None:
    spec = {f.name: (f.kind, f.required) for f in form_fields(SampleInput)}
    assert spec == {
        "days_overdue": ("number", True),
        "discount_rate": ("percent", True),
        "gl_balance": ("money", True),
        "open_dispute": ("boolean", False),
        "notes": ("textarea", False),
    }
    assert {f.name: f.kind for f in form_fields(SamplePolicy)} == {
        "variance_pct": "percent",
        "overdue_days": "number",
    }


def test_field_helpers_validate_input() -> None:
    data = SampleInput.model_validate(
        {"days_overdue": "45", "discount_rate": "6", "gl_balance": "-120.50"}
    )
    assert data.days_overdue == 45
    assert data.discount_rate == Decimal("6")
    assert data.gl_balance == Decimal("-120.50")
    assert data.open_dispute is False and data.notes is None

    for bad in ({"days_overdue": "4.5"}, {"days_overdue": "-1"}, {"discount_rate": "-101"}):
        with pytest.raises(ValidationError):
            SampleInput.model_validate(
                {"days_overdue": "1", "discount_rate": "1", "gl_balance": "0", **bad}
            )

    # A half-filled draft still saves; a checkbox left out stays False (not empty), so the
    # saved draft validates against the full schema once the rest is filled in
    draft = draft_schema(SampleInput).model_validate({}).model_dump()
    assert draft["days_overdue"] is None
    assert draft["open_dispute"] is False


def test_tolerance_check_match_within_and_mismatch() -> None:
    def check(difference: str) -> tuple[str, FlagSeverity, str]:
        f = tolerance_check(
            Decimal(difference),
            Decimal("100"),
            subject="AR",
            other="the counterparty AP",
            tolerance_name="matching",
            match_code="IC_MATCH",
            mismatch_code="IC_MISMATCH",
        )
        return f.code, f.severity, f.message

    assert check("0.00") == ("IC_MATCH", FlagSeverity.PASS, "AR matches the counterparty AP")
    assert check("-60") == (
        "IC_MATCH",
        FlagSeverity.PASS,
        "AR is within the 100.00 matching tolerance (difference -60.00)",
    )
    assert check("1000") == (
        "IC_MISMATCH",
        FlagSeverity.HIGH,
        "AR differs from the counterparty AP by 1,000.00",
    )


def test_over_limit_and_missing_skip_what_is_off_or_empty() -> None:
    def over(value: Decimal | None, limit: Decimal | None) -> bool:
        return over_limit(value, limit, code="OVER", message="Over") is not None

    assert over(Decimal("285"), Decimal("200"))
    assert not over(Decimal("200"), Decimal("200"))
    assert not over(Decimal("285"), None)  # threshold turned off
    assert not over(None, Decimal("200"))  # optional input left empty

    assert missing(None, code="NO_GL", message="No GL") is not None
    assert missing("", code="NO_GL", message="No GL") is not None
    assert missing("6100", code="NO_GL", message="No GL") is None


def test_formatting() -> None:
    assert money(Decimal("12500")) == "12,500.00"
    assert percent(Decimal("8.000")) == "8%"
    assert percent(Decimal("2.50")) == "2.5%"
