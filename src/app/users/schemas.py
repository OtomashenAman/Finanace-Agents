import uuid
from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, EmailStr, Field

from src.app.agent_catalog.models import AgentCapacity
from src.app.auth.models import UserRole

# Login accepts up to 256 characters; new passwords must be long enough to resist guessing
PASSWORD_MIN_LENGTH = 12
Password = Annotated[str, Field(min_length=PASSWORD_MIN_LENGTH, max_length=256)]
FullName = Annotated[str, Field(min_length=1, max_length=200)]


class AssignmentIn(BaseModel):
    agent_key: str = Field(max_length=64)
    # Users prepare; approving is for Finance Admins only
    capacity: Literal[AgentCapacity.PREPARER] = AgentCapacity.PREPARER


class AssignmentOut(BaseModel):
    agent_key: str
    agent_name: str
    capacity: AgentCapacity


class UserCreate(BaseModel):
    email: EmailStr
    full_name: FullName
    role: UserRole = UserRole.USER
    password: Password
    assignments: list[AssignmentIn] = []


class UserUpdate(BaseModel):
    """Partial update: omitted fields stay as they are."""

    full_name: FullName | None = None
    role: UserRole | None = None
    is_active: bool | None = None


class PasswordReset(BaseModel):
    password: Password


class AssignmentsUpdate(BaseModel):
    """The complete set of assignments; anything not listed is removed."""

    assignments: list[AssignmentIn]


class ManagedUser(BaseModel):
    id: uuid.UUID
    email: str
    full_name: str
    role: UserRole
    is_active: bool
    is_locked: bool
    last_login_at: datetime | None
    created_at: datetime
    assignments: list[AssignmentOut]
