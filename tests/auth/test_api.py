from datetime import timedelta
from typing import Annotated

import jwt
import pytest
from fastapi import Depends, FastAPI
from httpx import ASGITransport, AsyncClient, Response
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.audit.models import AuditEvent
from src.app.auth.dependencies import require_roles
from src.app.auth.models import RefreshToken, User, UserRole
from src.app.auth.security import JWT_ALGORITHM, JWT_ISSUER, create_access_token, hash_password
from src.app.common.clock import utcnow
from src.app.core.config import get_settings
from src.app.core.errors import register_exception_handlers
from src.app.main import app

EMAIL = "ap.analyst@example.com"
PASSWORD = "Correct-Horse-Battery-1"
LOGIN, REFRESH, LOGOUT, ME = (f"/api/v1/auth/{p}" for p in ("login", "refresh", "logout", "me"))


@pytest.fixture
async def user(db: AsyncSession) -> User:
    user = User(
        email=EMAIL,
        full_name="AP Analyst",
        role=UserRole.USER,
        password_hash=hash_password(PASSWORD),
    )
    db.add(user)
    await db.commit()
    return user


async def login(client: AsyncClient, email: str = EMAIL, password: str = PASSWORD) -> Response:
    return await client.post(LOGIN, json={"email": email, "password": password})


def set_cookie(response: Response, name: str) -> str:
    return next(c for c in response.headers.get_list("set-cookie") if c.startswith(f"{name}="))


async def post_with_cookie(path: str, cookie: str) -> Response:
    """Send one specific cookie value, bypassing any client cookie jar."""
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test", headers={"Cookie": cookie}
    ) as c:
        return await c.post(path)


async def event_types(db: AsyncSession) -> list[str]:
    rows = await db.scalars(select(AuditEvent.event_type).order_by(AuditEvent.created_at))
    return list(rows)


# --- login --------------------------------------------------------------------------------


async def test_login_sets_httponly_cookies_and_returns_user(
    client: AsyncClient, user: User
) -> None:
    r = await login(client)

    assert r.status_code == 200
    body = r.json()
    assert body["email"] == EMAIL
    assert body["role"] == "user"
    assert "password_hash" not in body

    access = set_cookie(r, "facc_access")
    refresh = set_cookie(r, "facc_refresh")
    for cookie in (access, refresh):
        assert "HttpOnly" in cookie
        assert "SameSite=lax" in cookie
    assert "Path=/api;" in access
    assert "Path=/api/v1/auth" in refresh


async def test_login_email_is_case_insensitive(client: AsyncClient, user: User) -> None:
    assert (await login(client, email=EMAIL.upper())).status_code == 200


async def test_wrong_password_and_unknown_email_look_identical(
    client: AsyncClient, user: User
) -> None:
    wrong_password = await login(client, password="nope")
    unknown_email = await login(client, email="nobody@example.com")

    expected = {"detail": {"code": "invalid_credentials", "message": "Invalid email or password."}}
    assert wrong_password.status_code == unknown_email.status_code == 401
    assert wrong_password.json() == unknown_email.json() == expected


async def test_account_locks_after_max_failed_attempts(client: AsyncClient, user: User) -> None:
    attempts = get_settings().login_max_attempts
    for _ in range(attempts - 1):
        assert (await login(client, password="nope")).status_code == 401

    locked = await login(client, password="nope")
    assert locked.status_code == 423
    assert locked.json()["detail"]["code"] == "account_locked"

    # Even the right password is refused while locked
    assert (await login(client)).status_code == 423


async def test_inactive_user_cannot_login(
    client: AsyncClient, user: User, db: AsyncSession
) -> None:
    await db.execute(update(User).values(is_active=False))
    await db.commit()

    r = await login(client)
    assert r.status_code == 401
    assert r.json()["detail"]["code"] == "invalid_credentials"


async def test_invalid_email_format_is_rejected(client: AsyncClient) -> None:
    assert (await login(client, email="not-an-email")).status_code == 422


# --- session ------------------------------------------------------------------------------


async def test_me_requires_authentication(client: AsyncClient) -> None:
    r = await client.get(ME)
    assert r.status_code == 401
    assert r.json()["detail"]["code"] == "not_authenticated"


async def test_me_returns_current_user_after_login(client: AsyncClient, user: User) -> None:
    await login(client)
    r = await client.get(ME)
    assert r.status_code == 200
    assert r.json()["email"] == EMAIL
    assert r.json()["last_login_at"] is not None


async def test_expired_access_token_is_rejected_with_specific_code(user: User) -> None:
    now = utcnow()
    token = jwt.encode(
        {
            "sub": str(user.id),
            "type": "access",
            "iss": JWT_ISSUER,
            "iat": now - timedelta(hours=1),
            "exp": now - timedelta(minutes=1),
        },
        get_settings().secret_key.get_secret_value(),
        algorithm=JWT_ALGORITHM,
    )
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
        headers={"Cookie": f"facc_access={token}"},
    ) as c:
        r = await c.get(ME)
    assert r.status_code == 401
    assert r.json()["detail"]["code"] == "token_expired"


async def test_tampered_access_token_is_rejected(client: AsyncClient, user: User) -> None:
    token = create_access_token(user.id, user.role.value)
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
        headers={"Cookie": f"facc_access={token[:-2]}xx"},
    ) as c:
        assert (await c.get(ME)).status_code == 401


# --- refresh rotation ---------------------------------------------------------------------


async def test_refresh_rotates_the_refresh_token(client: AsyncClient, user: User) -> None:
    await login(client)
    old = client.cookies["facc_refresh"]

    r = await client.post(REFRESH)

    assert r.status_code == 204
    assert client.cookies["facc_refresh"] != old
    assert (await client.get(ME)).status_code == 200


async def test_refresh_without_cookie_fails(client: AsyncClient) -> None:
    r = await client.post(REFRESH)
    assert r.status_code == 401
    assert r.json()["detail"]["code"] == "invalid_refresh_token"


async def test_reuse_within_grace_window_keeps_session(client: AsyncClient, user: User) -> None:
    """Two tabs refreshing at once: the loser gets 401 but the session survives."""
    await login(client)
    old = client.cookies["facc_refresh"]
    assert (await client.post(REFRESH)).status_code == 204

    assert (await post_with_cookie(REFRESH, f"facc_refresh={old}")).status_code == 401
    assert (await client.post(REFRESH)).status_code == 204


async def test_reuse_after_grace_window_revokes_whole_login(
    client: AsyncClient, user: User, db: AsyncSession
) -> None:
    await login(client)
    stolen = client.cookies["facc_refresh"]
    assert (await client.post(REFRESH)).status_code == 204
    current = client.cookies["facc_refresh"]

    # Make the earlier rotation look older than the grace window
    await db.execute(
        update(RefreshToken)
        .where(RefreshToken.revoked_at.is_not(None))
        .values(revoked_at=utcnow() - timedelta(minutes=5))
    )
    await db.commit()

    assert (await post_with_cookie(REFRESH, f"facc_refresh={stolen}")).status_code == 401
    # The legitimate (newest) token is revoked too
    assert (await post_with_cookie(REFRESH, f"facc_refresh={current}")).status_code == 401
    assert "auth.refresh_reuse_detected" in await event_types(db)


# --- logout -------------------------------------------------------------------------------


async def test_logout_clears_cookies_and_revokes_refresh_token(
    client: AsyncClient, user: User
) -> None:
    await login(client)
    old_refresh = client.cookies["facc_refresh"]

    r = await client.post(LOGOUT)

    assert r.status_code == 204
    assert "Max-Age=0" in set_cookie(r, "facc_access")
    assert "Max-Age=0" in set_cookie(r, "facc_refresh")
    assert (await client.get(ME)).status_code == 401
    assert (await post_with_cookie(REFRESH, f"facc_refresh={old_refresh}")).status_code == 401


async def test_logout_without_session_is_harmless(client: AsyncClient) -> None:
    assert (await client.post(LOGOUT)).status_code == 204


# --- audit + roles ------------------------------------------------------------------------


async def test_auth_events_are_audited(client: AsyncClient, user: User, db: AsyncSession) -> None:
    await login(client, password="nope")
    await login(client)
    await client.post(LOGOUT)

    assert await event_types(db) == ["auth.login_failed", "auth.login_success", "auth.logout"]
    failed = await db.scalar(select(AuditEvent).where(AuditEvent.event_type == "auth.login_failed"))
    assert failed is not None
    assert failed.actor_id == user.id
    assert failed.details == {"reason": "bad_password"}


async def test_require_roles_blocks_other_roles(user: User) -> None:
    probe = FastAPI()
    register_exception_handlers(probe)

    @probe.get("/admin-only")
    async def admin_only(
        _: Annotated[User, Depends(require_roles(UserRole.FINANCE_ADMIN))],
    ) -> dict[str, bool]:
        return {"ok": True}

    token = create_access_token(user.id, user.role.value)
    async with AsyncClient(
        transport=ASGITransport(app=probe),
        base_url="http://test",
        headers={"Cookie": f"facc_access={token}"},
    ) as c:
        r = await c.get("/admin-only")
    assert r.status_code == 403
    assert r.json()["detail"]["code"] == "permission_denied"


# --- per-tab sessions -----------------------------------------------------------------------


async def test_each_tab_slot_keeps_its_own_session(
    client: AsyncClient, user: User, db: AsyncSession
) -> None:
    """One browser (one cookie jar), two tabs: an admin and a user signed in side by side."""
    db.add(
        User(
            email="admin@example.com",
            full_name="Admin",
            role=UserRole.FINANCE_ADMIN,
            password_hash=hash_password(PASSWORD),
        )
    )
    await db.commit()
    tab_a, tab_b = {"X-Session-Slot": "tabaaaa1"}, {"X-Session-Slot": "tabbbbb2"}

    r = await client.post(LOGIN, json={"email": EMAIL, "password": PASSWORD}, headers=tab_a)
    assert r.status_code == 200
    assert "facc_access_tabaaaa1=" in r.headers["set-cookie"]
    r = await client.post(
        LOGIN, json={"email": "admin@example.com", "password": PASSWORD}, headers=tab_b
    )
    assert r.status_code == 200

    assert (await client.get(ME, headers=tab_a)).json()["email"] == EMAIL
    assert (await client.get(ME, headers=tab_b)).json()["email"] == "admin@example.com"
    assert (await client.get(ME)).status_code == 401  # no slot: the plain cookie, never set

    assert (await client.post(REFRESH, headers=tab_a)).status_code == 204
    await client.post(LOGOUT, headers=tab_a)
    assert (await client.get(ME, headers=tab_a)).status_code == 401
    assert (await client.get(ME, headers=tab_b)).json()["email"] == "admin@example.com"


async def test_malformed_slot_falls_back_to_the_plain_cookie(
    client: AsyncClient, user: User
) -> None:
    await login(client)
    r = await client.get(ME, headers={"X-Session-Slot": "../../etc"})
    assert r.json()["email"] == EMAIL
