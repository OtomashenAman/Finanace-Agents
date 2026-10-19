import hashlib
import secrets
import uuid
from datetime import timedelta
from functools import lru_cache
from typing import Any

import jwt
from pwdlib import PasswordHash

from src.app.common.clock import utcnow
from src.app.core.config import get_settings

JWT_ALGORITHM = "HS256"
JWT_ISSUER = "finance-acc"

_password_hash = PasswordHash.recommended()  # argon2id


def hash_password(password: str) -> str:
    return _password_hash.hash(password)


def verify_password(password: str, password_hash: str) -> tuple[bool, str | None]:
    """Return (valid, new_hash). new_hash is set when the stored hash needs an upgrade."""
    return _password_hash.verify_and_update(password, password_hash)


@lru_cache
def _dummy_hash() -> str:
    return hash_password(secrets.token_urlsafe(16))


def burn_password_check(password: str) -> None:
    """Spend the same time as a real check so unknown emails can't be detected by timing."""
    _password_hash.verify(password, _dummy_hash())


def create_access_token(user_id: uuid.UUID, role: str) -> str:
    settings = get_settings()
    now = utcnow()
    payload = {
        "sub": str(user_id),
        "role": role,
        "type": "access",
        "iss": JWT_ISSUER,
        "iat": now,
        "exp": now + timedelta(minutes=settings.access_token_ttl_minutes),
        "jti": uuid.uuid4().hex,
    }
    return jwt.encode(payload, settings.secret_key.get_secret_value(), algorithm=JWT_ALGORITHM)


def decode_access_token(token: str) -> dict[str, Any]:
    """Raise jwt.ExpiredSignatureError / jwt.InvalidTokenError on a bad token."""
    payload: dict[str, Any] = jwt.decode(
        token,
        get_settings().secret_key.get_secret_value(),
        algorithms=[JWT_ALGORITHM],
        issuer=JWT_ISSUER,
        options={"require": ["sub", "exp", "iat", "type"]},
    )
    if payload["type"] != "access":
        raise jwt.InvalidTokenError("not an access token")
    return payload


def new_refresh_token() -> str:
    return secrets.token_urlsafe(48)


def hash_token(token: str) -> str:
    """Refresh tokens are stored only as SHA-256 hashes."""
    return hashlib.sha256(token.encode()).hexdigest()
