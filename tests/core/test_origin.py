import pytest
from httpx import AsyncClient

from src.app.auth.models import UserRole
from src.app.core.config import Settings
from src.app.core.origin import origin_allowed
from tests.conftest import DEFAULT_PASSWORD, MakeUser


def _settings(**overrides: object) -> Settings:
    base: dict[str, object] = {
        "database_url": "postgresql+asyncpg://u:p@localhost/x",
        "secret_key": "s",
        "public_base_url": "https://finance.example.com",
    }
    return Settings(**{**base, **overrides})  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("origin", "allowed"),
    [
        ("https://finance.example.com", True),
        ("https://FINANCE.example.com", True),
        ("https://finance.example.com.evil.io", False),
        ("http://finance.example.com", False),  # scheme is part of the origin
        ("https://evil.example.com", False),
        ("null", False),
        ("", False),
    ],
)
def test_origin_matches_public_base_url(origin: str, allowed: bool) -> None:
    assert origin_allowed(origin, _settings()) is allowed


def test_extra_cors_origins_are_allowed() -> None:
    settings = _settings(cors_origins=["https://admin.example.com"])
    assert origin_allowed("https://admin.example.com", settings)


def test_localhost_only_outside_production() -> None:
    assert origin_allowed("http://localhost:8082", _settings())
    assert origin_allowed("http://127.0.0.1:5173", _settings())
    prod = _settings(environment="production", secret_key="x" * 40, data_encryption_key="k")
    assert not origin_allowed("http://localhost:8082", prod)
    assert origin_allowed("https://finance.example.com", prod)


async def test_cross_site_post_is_refused(client: AsyncClient, make_user: MakeUser) -> None:
    await make_user("a@example.com", UserRole.FINANCE_ADMIN)
    login = {"email": "a@example.com", "password": DEFAULT_PASSWORD}

    r = await client.post(
        "/api/v1/auth/login", json=login, headers={"Origin": "https://evil.example.com"}
    )
    assert r.status_code == 403
    assert r.json()["detail"]["code"] == "cross_origin_request"

    r = await client.post(
        "/api/v1/auth/login", json=login, headers={"Sec-Fetch-Site": "cross-site"}
    )
    assert r.status_code == 403


async def test_same_origin_and_non_browser_posts_pass(
    client: AsyncClient, make_user: MakeUser
) -> None:
    await make_user("a@example.com", UserRole.FINANCE_ADMIN)
    login = {"email": "a@example.com", "password": DEFAULT_PASSWORD}

    r = await client.post(
        "/api/v1/auth/login", json=login, headers={"Origin": "http://localhost:8081"}
    )
    assert r.status_code == 200
    assert "samesite=strict" in r.headers["set-cookie"].lower()

    r = await client.post("/api/v1/auth/login", json=login)  # no Origin: not a browser
    assert r.status_code == 200


async def test_reads_are_never_blocked(client: AsyncClient) -> None:
    r = await client.get("/health", headers={"Origin": "https://evil.example.com"})
    assert r.status_code == 200
