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
    label: str, *, required: bool = True, max_length: int = 200, help: str | None = None
) -> Any:
    return Field(
        ... if required else None,
        title=label,
        description=help,
        min_length=1 if required else None,
        max_length=max_length,
        json_schema_extra={"ui": "text"},
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
