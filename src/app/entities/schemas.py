import uuid
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field

Code = Annotated[str, Field(min_length=1, max_length=20, pattern=r"^[A-Za-z0-9_-]+$")]
Name = Annotated[str, Field(min_length=1, max_length=200)]


class EntityOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    code: str
    name: str
    is_active: bool


class EntityCreate(BaseModel):
    code: Code
    name: Name


class EntityUpdate(BaseModel):
    """Partial update: omitted fields stay as they are."""

    name: Name | None = None
    is_active: bool | None = None


class EntityRef(BaseModel):
    """How a run shows its entity."""

    id: uuid.UUID
    code: str
    name: str
