"""QuickBooks Online: Intuit OAuth 2.0 and the accounting API, mapped to canonical records."""

import contextlib
import urllib.parse
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

import httpx
from pydantic import ValidationError

from src.app.common.clock import utcnow
from src.app.core.config import get_settings
from src.app.data_sources.models import IntegrationEnvironment
from src.app.data_sources.records import (
    Account,
    Bill,
    PurchaseOrder,
    Record,
    RecordType,
    Vendor,
)

AUTHORIZE_URL = "https://appcenter.intuit.com/connect/oauth2"
TOKEN_URL = "https://oauth.platform.intuit.com/oauth2/v1/tokens/bearer"  # noqa: S105 - a URL
REVOKE_URL = "https://developer.api.intuit.com/v2/oauth2/tokens/revoke"
SCOPE = "com.intuit.quickbooks.accounting"
API_BASE = {
    IntegrationEnvironment.SANDBOX: "https://sandbox-quickbooks.api.intuit.com",
    IntegrationEnvironment.PRODUCTION: "https://quickbooks.api.intuit.com",
}
MINOR_VERSION = "75"
PAGE_SIZE = 1000
CALLBACK_PATH = "/api/v1/data-sources/quickbooks/callback"

# Tests swap this for an httpx.MockTransport; None means real network calls
transport: httpx.AsyncBaseTransport | None = None


class QuickBooksError(Exception):
    """Intuit refused or failed a call; the message is safe to show the user."""


class ReauthorizationRequired(QuickBooksError):
    """The refresh token is expired or revoked: the user must authorize again."""


@dataclass(frozen=True)
class AppCredentials:
    client_id: str
    client_secret: str
    environment: IntegrationEnvironment


@dataclass(frozen=True)
class Tokens:
    access_token: str
    refresh_token: str
    access_expires_at: datetime

    def to_json(self) -> dict[str, str]:
        return {
            "access_token": self.access_token,
            "refresh_token": self.refresh_token,
            "access_expires_at": self.access_expires_at.isoformat(),
        }

    @classmethod
    def from_json(cls, value: dict[str, Any]) -> "Tokens":
        return cls(
            access_token=value["access_token"],
            refresh_token=value["refresh_token"],
            access_expires_at=datetime.fromisoformat(value["access_expires_at"]),
        )

    @property
    def expired(self) -> bool:
        return self.access_expires_at <= utcnow() + timedelta(minutes=2)


def redirect_uri() -> str:
    """Must match a Redirect URI registered in the Intuit app, character for character."""
    return get_settings().public_base_url.rstrip("/") + CALLBACK_PATH


def authorization_url(app: AppCredentials, state: str) -> str:
    params = {
        "client_id": app.client_id,
        "redirect_uri": redirect_uri(),
        "response_type": "code",
        "scope": SCOPE,
        "state": state,
    }
    return f"{AUTHORIZE_URL}?{urllib.parse.urlencode(params)}"


def client() -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=transport, timeout=get_settings().data_sync_timeout_seconds)


def _error_code(resp: httpx.Response) -> str | None:
    try:
        return str(resp.json().get("error"))
    except ValueError:
        return None


async def _token_request(app: AppCredentials, data: dict[str, str]) -> Tokens:
    async with client() as http:
        try:
            resp = await http.post(
                TOKEN_URL,
                data=data,
                auth=(app.client_id, app.client_secret),
                headers={"Accept": "application/json"},
            )
        except httpx.HTTPError as exc:
            raise QuickBooksError("Couldn't reach QuickBooks. Try again in a moment.") from exc
    if resp.status_code == 400 and _error_code(resp) == "invalid_grant":
        raise ReauthorizationRequired("QuickBooks access expired or was revoked.")
    if resp.status_code == 401:
        raise QuickBooksError(
            "QuickBooks rejected the app credentials (check the Client ID/Secret)."
        )
    if resp.is_error:
        raise QuickBooksError(f"QuickBooks token request failed ({resp.status_code}).")
    body = resp.json()
    return Tokens(
        access_token=body["access_token"],
        refresh_token=body["refresh_token"],
        access_expires_at=utcnow() + timedelta(seconds=int(body.get("expires_in", 3600))),
    )


async def exchange_code(app: AppCredentials, code: str) -> Tokens:
    return await _token_request(
        app, {"grant_type": "authorization_code", "code": code, "redirect_uri": redirect_uri()}
    )


async def refresh(app: AppCredentials, refresh_token: str) -> Tokens:
    """Intuit rotates the refresh token: always store the returned one."""
    return await _token_request(
        app, {"grant_type": "refresh_token", "refresh_token": refresh_token}
    )


async def revoke(app: AppCredentials, refresh_token: str) -> None:
    """Best effort: disconnecting locally must not depend on Intuit being reachable."""
    async with client() as http:
        with contextlib.suppress(httpx.HTTPError):
            await http.post(
                REVOKE_URL,
                json={"token": refresh_token},
                auth=(app.client_id, app.client_secret),
                headers={"Accept": "application/json"},
            )


class Api:
    def __init__(self, client: httpx.AsyncClient, app: AppCredentials, realm_id: str, token: str):
        self._client = client
        self._base = f"{API_BASE[app.environment]}/v3/company/{realm_id}"
        self._headers = {"Authorization": f"Bearer {token}", "Accept": "application/json"}

    async def _get(self, path: str, **params: str) -> dict[str, Any]:
        try:
            resp = await self._client.get(
                f"{self._base}/{path}",
                params={**params, "minorversion": MINOR_VERSION},
                headers=self._headers,
            )
        except httpx.HTTPError as exc:
            raise QuickBooksError("Couldn't reach QuickBooks. Try again in a moment.") from exc
        if resp.status_code in (401, 403):
            raise ReauthorizationRequired("QuickBooks no longer accepts this connection.")
        if resp.is_error:
            raise QuickBooksError(f"QuickBooks API request failed ({resp.status_code}).")
        result: dict[str, Any] = resp.json()
        return result

    async def _post(self, path: str, body: dict[str, Any]) -> dict[str, Any]:
        try:
            resp = await self._client.post(
                f"{self._base}/{path}",
                params={"minorversion": MINOR_VERSION},
                headers={**self._headers, "Content-Type": "application/json"},
                json=body,
            )
        except httpx.HTTPError as exc:
            raise QuickBooksError("Couldn't reach QuickBooks. Try again in a moment.") from exc
        if resp.status_code in (401, 403):
            raise ReauthorizationRequired("QuickBooks no longer accepts this connection.")
        if resp.is_error:
            raise QuickBooksError(f"QuickBooks rejected the update ({resp.status_code}).")
        result: dict[str, Any] = resp.json()
        return result

    async def get_bill(self, bill_id: str) -> dict[str, Any]:
        bill: dict[str, Any] = (await self._get(f"bill/{bill_id}")).get("Bill", {})
        return bill

    async def set_bill_note(self, bill_id: str, sync_token: str, note: str) -> dict[str, Any]:
        """Sparse update: only the private note changes (amounts, lines, accounts untouched)."""
        body = {"Id": bill_id, "SyncToken": sync_token, "sparse": True, "PrivateNote": note}
        bill: dict[str, Any] = (await self._post("bill", body)).get("Bill", {})
        return bill

    async def company_name(self, realm_id: str) -> str | None:
        body = await self._get(f"companyinfo/{realm_id}")
        name = body.get("CompanyInfo", {}).get("CompanyName")
        return str(name) if name else None

    async def query_all(self, entity: str) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        start = 1
        while True:
            # entity comes from fetch_all's fixed list, never from user input
            statement = f"SELECT * FROM {entity} STARTPOSITION {start} MAXRESULTS {PAGE_SIZE}"  # noqa: S608
            page = (await self._get("query", query=statement)).get("QueryResponse", {})
            batch = page.get(entity, [])
            rows.extend(batch)
            if len(batch) < PAGE_SIZE:
                return rows
            start += PAGE_SIZE


# --- mapping to canonical records -------------------------------------------------------


def _ref_name(row: dict[str, Any], key: str) -> str | None:
    ref = row.get(key)
    return str(ref["name"]) if isinstance(ref, dict) and ref.get("name") else None


def _vendor(row: dict[str, Any]) -> Vendor:
    return Vendor(
        external_id=str(row["Id"]),
        name=row.get("DisplayName") or row.get("CompanyName") or f"Vendor {row['Id']}",
        email=(row.get("PrimaryEmailAddr") or {}).get("Address"),
        tax_id=row.get("TaxIdentifier"),
        active=bool(row.get("Active", True)),
    )


def _purchase_order(row: dict[str, Any]) -> PurchaseOrder:
    return PurchaseOrder(
        external_id=str(row["Id"]),
        po_number=row.get("DocNumber") or f"PO {row['Id']}",
        vendor_name=_ref_name(row, "VendorRef") or "Unknown vendor",
        total=row.get("TotalAmt", 0),
        status=row.get("POStatus"),
        po_date=row.get("TxnDate"),
    )


def _bill(row: dict[str, Any], po_numbers: dict[str, str]) -> Bill:
    linked_po = next(
        (t["TxnId"] for t in row.get("LinkedTxn", []) if t.get("TxnType") == "PurchaseOrder"),
        None,
    )
    account = next(
        (
            _ref_name(line.get("AccountBasedExpenseLineDetail", {}), "AccountRef")
            for line in row.get("Line", [])
            if line.get("AccountBasedExpenseLineDetail")
        ),
        None,
    )
    return Bill(
        external_id=str(row["Id"]),
        doc_number=row.get("DocNumber") or f"Bill {row['Id']}",
        vendor_name=_ref_name(row, "VendorRef") or "Unknown vendor",
        total=row.get("TotalAmt", 0),
        tax_total=(row.get("TxnTaxDetail") or {}).get("TotalTax"),
        bill_date=row.get("TxnDate"),
        due_date=row.get("DueDate"),
        po_number=po_numbers.get(str(linked_po)) if linked_po else None,
        account=account,
    )


def _account(row: dict[str, Any]) -> Account:
    return Account(
        external_id=str(row["Id"]),
        number=row.get("AcctNum"),
        name=row.get("FullyQualifiedName") or row.get("Name") or f"Account {row['Id']}",
        account_type=row.get("AccountType"),
    )


@dataclass
class Snapshot:
    company_name: str | None
    records: dict[RecordType, list[Record]]
    skipped: int  # rows QuickBooks returned that don't fit the canonical shape


async def fetch_all(qbo: Api, realm_id: str) -> Snapshot:
    """Everything the agents use, as canonical records."""
    raw = {
        entity: await qbo.query_all(entity)
        for entity in ("Vendor", "PurchaseOrder", "Bill", "Account")
    }
    po_numbers = {str(r["Id"]): r.get("DocNumber") or f"PO {r['Id']}" for r in raw["PurchaseOrder"]}
    mappers: dict[RecordType, tuple[str, Any]] = {
        RecordType.VENDOR: ("Vendor", _vendor),
        RecordType.PURCHASE_ORDER: ("PurchaseOrder", _purchase_order),
        RecordType.BILL: ("Bill", lambda row: _bill(row, po_numbers)),
        RecordType.ACCOUNT: ("Account", _account),
    }
    records: dict[RecordType, list[Record]] = {}
    skipped = 0
    for record_type, (entity, mapper) in mappers.items():
        records[record_type] = []
        for row in raw[entity]:
            try:
                records[record_type].append(mapper(row))
            except (ValidationError, KeyError):
                skipped += 1
    return Snapshot(await qbo.company_name(realm_id), records, skipped)
