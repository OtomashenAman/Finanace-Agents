import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, EmailStr, Field

from src.app.auth.models import UserRole


class LoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=256)


class PasswordChange(BaseModel):
    current_password: str = Field(min_length=1, max_length=256)
    new_password: str = Field(min_length=12, max_length=256)  # users.schemas.PASSWORD_MIN_LENGTH


class ResetRequest(BaseModel):
    email: EmailStr


class ActingAdmin(BaseModel):
    id: uuid.UUID
    full_name: str
    email: str


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    email: str
    full_name: str
    role: UserRole
    last_login_at: datetime | None


class MeOut(UserOut):
    # This tab is a Finance Admin testing as this user (None: the user's own sign-in)
    acted_by: ActingAdmin | None = None
    # A Finance Admin who may open a tab as another user here (dev and demo only)
    can_act_as: bool = False


class ActAsRequest(BaseModel):
    user_id: uuid.UUID
    # the new tab's session slot (the request itself comes from the admin's own tab)
    slot: str = Field(pattern=r"^[a-z0-9]{8,32}$")
