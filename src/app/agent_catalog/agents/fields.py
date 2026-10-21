"""Building blocks for agent input forms.

An agent's Input model is a normal Pydantic model built from these helpers. The same model
validates the API, drives the generated frontend form, and is sent to the LLM.
"""

from copy import copy
from decimal import Decimal
from typing import Any, Literal

from annotated_types import MaxLen
from pydantic import BaseModel, ConfigDict, Field, create_model

FieldKind = Literal["text", "textarea", "money", "number", "percent", "boolean"]


class AgentInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")


def text_field(
    label: str,
    *,
    required: bool = True,
    max_length: int = 200,
    pattern: str | None = None,
    help: str | None = None,
) -> Any:
    return Field(
        ... if required else None,
        title=label,
        description=help,
        min_length=1 if required else None,
        max_length=max_length,
        pattern=pattern,
        json_schema_extra={"ui": "text"},
    )


def textarea_field(
    label: str, *, required: bool = False, max_length: int = 4000, help: str | None = None
) -> Any:
    """Free text (notes, clauses, assumptions): optional by default."""
    return Field(
        ... if required else None,
        title=label,
        description=help,
        min_length=1 if required else None,
        max_length=max_length,
        json_schema_extra={"ui": "textarea"},
    )


def money_field(
    label: str, *, required: bool = True, gt: Decimal | None = None, help: str | None = None
) -> Any:
    return Field(
        ... if required else None,
        title=label,
        description=help,
        gt=gt,
        ge=None if gt is not None else Decimal(0),
        max_digits=18,
        decimal_places=2,
        json_schema_extra={"ui": "money"},
    )


def signed_money_field(label: str, *, required: bool = True, help: str | None = None) -> Any:
    """An amount that may be negative (e.g. a balance or a variance)."""
    return Field(
        ... if required else None,
        title=label,
        description=help,
        max_digits=18,
        decimal_places=2,
        json_schema_extra={"ui": "money"},
    )


def number_field(
    label: str,
    *,
    required: bool = True,
    ge: Decimal | int | None = 0,
    le: Decimal | int | None = None,
    help: str | None = None,
) -> Any:
    """A count or plain number. Annotate as int for whole numbers (days, months, items)."""
    return Field(
        ... if required else None,
        title=label,
        description=help,
        ge=ge,
        le=le,
        json_schema_extra={"ui": "number"},
    )


def percent_field(
    label: str,
    *,
    required: bool = True,
    ge: Decimal | None = Decimal(-100),
    le: Decimal | None = Decimal(1000),
    help: str | None = None,
) -> Any:
    """A percentage as entered (6 means 6%), so it may be negative for a change."""
    return Field(
        ... if required else None,
        title=label,
        description=help,
        ge=ge,
        le=le,
        max_digits=9,
        decimal_places=4,
        json_schema_extra={"ui": "percent"},
    )


def bool_field(label: str, *, default: bool = False, help: str | None = None) -> Any:
    """A checkbox: always sent, so it has a default rather than being required."""
    return Field(default, title=label, description=help, json_schema_extra={"ui": "boolean"})


class PolicySettings(BaseModel):
    """An agent's thresholds: every field has a default, admins version their changes."""

    model_config = ConfigDict(extra="forbid")


def money_setting(label: str, default: Decimal | None, *, help: str | None = None) -> Any:
    """A threshold amount (None = the check is off)."""
    return Field(
        default,
        title=label,
        description=help,
        ge=Decimal(0),
        max_digits=18,
        decimal_places=2,
        json_schema_extra={"ui": "money"},
    )


def percent_setting(label: str, default: Decimal | None, *, help: str | None = None) -> Any:
    """A threshold percentage, as entered (5 means 5%; None = the check is off)."""
    return Field(
        default,
        title=label,
        description=help,
        ge=Decimal(0),
        le=Decimal(1000),
        max_digits=9,
        decimal_places=4,
        json_schema_extra={"ui": "percent"},
    )


def number_setting(label: str, default: int | None, *, help: str | None = None) -> Any:
    """A threshold count, e.g. days or items (None = the check is off)."""
    return Field(default, title=label, description=help, ge=0, json_schema_extra={"ui": "number"})


class FormField(BaseModel):
    name: str
    label: str
    kind: FieldKind
    required: bool
    help: str | None
    max_length: int | None


def form_fields(schema: type[BaseModel]) -> list[FormField]:
    """Describe an Input model for the frontend form renderer."""
    fields = []
    for name, info in schema.model_fields.items():
        extra = info.json_schema_extra if isinstance(info.json_schema_extra, dict) else {}
        max_length = next((m.max_length for m in info.metadata if isinstance(m, MaxLen)), None)
        fields.append(
            FormField(
                name=name,
                label=info.title or name,
                kind=extra.get("ui", "text"),
                required=info.is_required(),
                help=info.description,
                max_length=max_length,
            )
        )
    return fields


def draft_schema(schema: type[BaseModel]) -> type[BaseModel]:
    """Same fields and constraints, all optional: lets users save a half-filled form."""
    fields: dict[str, Any] = {}
    for name, info in schema.model_fields.items():
        optional = copy(info)
        optional.default = None
        annotation: Any = info.annotation
        fields[name] = (annotation | None, optional)
    model: type[BaseModel] = create_model(f"{schema.__name__}Draft", __base__=AgentInput, **fields)
    return model
