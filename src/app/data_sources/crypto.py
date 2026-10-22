"""Encryption at rest for data source secrets (OAuth tokens, client secrets)."""

import base64
import hashlib
import json
from functools import lru_cache
from typing import Any

from cryptography.fernet import Fernet, InvalidToken

from src.app.core.config import get_settings


@lru_cache
def _fernet() -> Fernet:
    settings = get_settings()
    if settings.data_encryption_key is not None:
        return Fernet(settings.data_encryption_key.get_secret_value().encode())
    # Development/test fallback (production requires DATA_ENCRYPTION_KEY, see config.py)
    digest = hashlib.sha256(
        b"finance-acc/data-sources:" + settings.secret_key.get_secret_value().encode()
    )
    return Fernet(base64.urlsafe_b64encode(digest.digest()))


def encrypt(value: str) -> str:
    return _fernet().encrypt(value.encode()).decode()


def decrypt(token: str) -> str:
    try:
        return _fernet().decrypt(token.encode()).decode()
    except InvalidToken as exc:  # wrong/rotated key: the secret must be entered again
        raise ValueError("Stored secret can't be decrypted with the current key") from exc


def encrypt_json(value: dict[str, Any]) -> str:
    return encrypt(json.dumps(value))


def decrypt_json(token: str) -> dict[str, Any]:
    result: dict[str, Any] = json.loads(decrypt(token))
    return result
