import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.audit.service import record_event
from src.app.auth.exceptions import (
    AccountLockedError,
    InvalidCredentialsError,
    InvalidRefreshTokenError,
)
from src.app.auth.models import RefreshToken, User
from src.app.auth.security import (
    burn_password_check,
    create_access_token,
    hash_token,
    new_refresh_token,
    verify_password,
)
from src.app.common.clock import utcnow
from src.app.common.context import RequestContext
from src.app.core.config import get_settings


@dataclass(frozen=True)
class IssuedTokens:
    access_token: str
    refresh_token: str


async def authenticate(
    session: AsyncSession, email: str, password: str, ctx: RequestContext
) -> User:
    """Check credentials with lockout + audit. Failed attempts are committed before raising."""
    settings = get_settings()
    email = email.strip().lower()
    now = utcnow()
    user = await session.scalar(select(User).where(User.email == email).with_for_update())

    if user is None:
        burn_password_check(password)
        record_event(session, "auth.login_failed", ctx, reason="unknown_email", email=email)
        await session.commit()
        raise InvalidCredentialsError

    if user.locked_until and user.locked_until > now:
        record_event(session, "auth.login_blocked", ctx, actor_id=user.id, reason="locked")
        await session.commit()
        raise AccountLockedError(user.locked_until)

    valid, new_hash = verify_password(password, user.password_hash)
    if not valid or not user.is_active:
        reason = "inactive" if valid else "bad_password"
        user.failed_login_attempts += 1
        record_event(session, "auth.login_failed", ctx, actor_id=user.id, reason=reason)
        if user.failed_login_attempts >= settings.login_max_attempts:
            user.locked_until = now + timedelta(minutes=settings.login_lockout_minutes)
            user.failed_login_attempts = 0
            record_event(session, "auth.account_locked", ctx, actor_id=user.id)
            await session.commit()
            raise AccountLockedError(user.locked_until)
        await session.commit()
        raise InvalidCredentialsError

    if new_hash:
        user.password_hash = new_hash
    user.failed_login_attempts = 0
    user.locked_until = None
    user.last_login_at = now
    record_event(session, "auth.login_success", ctx, actor_id=user.id)
    return user


def issue_tokens(
    session: AsyncSession,
    user: User,
    ctx: RequestContext,
    family_id: uuid.UUID | None = None,
) -> IssuedTokens:
    """Create an access token + a new refresh token row (caller commits)."""
    settings = get_settings()
    raw_refresh = new_refresh_token()
    session.add(
        RefreshToken(
            user_id=user.id,
            token_hash=hash_token(raw_refresh),
            family_id=family_id or uuid.uuid4(),
            expires_at=utcnow() + timedelta(days=settings.refresh_token_ttl_days),
            user_agent=ctx.user_agent[:512] if ctx.user_agent else None,
            ip=ctx.ip,
        )
    )
    return IssuedTokens(create_access_token(user.id, user.role.value), raw_refresh)


async def rotate_refresh_token(
    session: AsyncSession, raw_refresh: str, ctx: RequestContext
) -> tuple[User, IssuedTokens]:
    """Swap a valid refresh token for a new pair (caller commits). Detects token reuse."""
    settings = get_settings()
    now = utcnow()
    token = await session.scalar(
        select(RefreshToken)
        .where(RefreshToken.token_hash == hash_token(raw_refresh))
        .with_for_update()
    )
    if token is None:
        raise InvalidRefreshTokenError

    if token.revoked_at is not None:
        grace = timedelta(seconds=settings.refresh_reuse_grace_seconds)
        if now - token.revoked_at > grace:
            # A rotated-away token came back: assume theft, end every session of this login
            await _revoke_family(session, token.family_id, now)
            record_event(session, "auth.refresh_reuse_detected", ctx, actor_id=token.user_id)
            await session.commit()
        # Inside the grace window it's another tab that lost the race: reject quietly
        raise InvalidRefreshTokenError

    if token.expires_at <= now:
        raise InvalidRefreshTokenError

    user = await session.get(User, token.user_id)
    if user is None or not user.is_active:
        raise InvalidRefreshTokenError

    token.revoked_at = now
    return user, issue_tokens(session, user, ctx, family_id=token.family_id)


async def logout(session: AsyncSession, raw_refresh: str | None, ctx: RequestContext) -> None:
    """Revoke every refresh token of this login and audit it (caller commits)."""
    actor_id = None
    if raw_refresh:
        token = await session.scalar(
            select(RefreshToken).where(RefreshToken.token_hash == hash_token(raw_refresh))
        )
        if token is not None:
            actor_id = token.user_id
            await _revoke_family(session, token.family_id, utcnow())
    record_event(session, "auth.logout", ctx, actor_id=actor_id)


async def _revoke_family(session: AsyncSession, family_id: uuid.UUID, now: datetime) -> None:
    await session.execute(
        update(RefreshToken)
        .where(RefreshToken.family_id == family_id, RefreshToken.revoked_at.is_(None))
        .values(revoked_at=now)
    )


async def revoke_user_tokens(session: AsyncSession, user_id: uuid.UUID) -> None:
    """End every session of a user (password reset, deactivation). Caller commits."""
    await session.execute(
        update(RefreshToken)
        .where(RefreshToken.user_id == user_id, RefreshToken.revoked_at.is_(None))
        .values(revoked_at=utcnow())
    )
