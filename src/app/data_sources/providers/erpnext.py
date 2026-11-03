"""ERPNext (Frappe) REST client: token auth, paged reads, and the few writes the Finance POD
makes after a person approves them.

Every write carries our reference in the custom field `finance_acc_ref` (created by
scripts/erpnext_seed.py, or by an ERPNext admin on a client's site), and is looked up by it
first: a retried post finds the document the first attempt made instead of creating a second.
"""

import asyncio
import json
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any
from urllib.parse import quote, urlsplit

import httpx

from src.app.core.config import get_settings

PAGE = 500
CONCURRENCY = 6
REF_FIELD = "finance_acc_ref"
transport: httpx.AsyncBaseTransport | None = None  # tests swap in an httpx.MockTransport


class ErpNextError(Exception):
    """ERPNext refused or couldn't be reached (the message says which)."""


class ErpNextAuthError(ErpNextError):
    pass


def _doc_path(doctype: str, name: str) -> str:
    """A document's URL: its name quoted whole (names may hold "%", "&" or "/")."""
    return f"/api/resource/{doctype}/{quote(name, safe='')}"


@dataclass(frozen=True)
class Credentials:
    base_url: str
    api_key: str
    api_secret: str


def check_base_url(url: str) -> str:
    """http(s) URL with a host; in production only https and an allowed host (the server
    calls this URL, so it must not be pointed at internal services)."""
    parts = urlsplit(url.strip())
    if parts.scheme not in ("http", "https") or not parts.hostname:
        raise ErpNextError("Enter the ERPNext address, e.g. https://erp.example.com.")
    settings = get_settings()
    allowed = {h.strip().lower() for h in settings.erpnext_allowed_hosts.split(",") if h.strip()}
    if settings.is_production:
        if parts.scheme != "https":
            raise ErpNextError("ERPNext must be reached over https in production.")
        if parts.hostname.lower() not in allowed:
            raise ErpNextError("This ERPNext host isn't allowed (ERPNEXT_ALLOWED_HOSTS).")
    elif allowed and parts.hostname.lower() not in allowed:
        raise ErpNextError("This ERPNext host isn't allowed (ERPNEXT_ALLOWED_HOSTS).")
    return f"{parts.scheme}://{parts.netloc}"


def _message(resp: httpx.Response) -> str:
    try:
        body = resp.json()
    except ValueError:
        return resp.text[:300] or f"HTTP {resp.status_code}"
    server = body.get("_server_messages")
    if server:
        try:
            first = json.loads(json.loads(server)[0])
            return str(first.get("message", first))[:300]
        except (ValueError, TypeError, IndexError, AttributeError):
            pass
    return str(body.get("exception") or body.get("message") or body)[:300]


class Api:
    def __init__(self, creds: Credentials) -> None:
        self.creds = creds
        self.http = httpx.AsyncClient(
            base_url=creds.base_url,
            headers={"Authorization": f"token {creds.api_key}:{creds.api_secret}"},
            timeout=60,
            transport=transport,
        )
        self._limit = asyncio.Semaphore(CONCURRENCY)

    async def __aenter__(self) -> "Api":
        return self

    async def __aexit__(self, *_: object) -> None:
        await self.http.aclose()

    async def _send(self, method: str, path: str, **kw: Any) -> Any:
        async with self._limit:
            try:
                resp = await self.http.request(method, path, **kw)
            except httpx.HTTPError as exc:
                raise ErpNextError(
                    f"Can't reach ERPNext at {self.http.base_url}: {exc.__class__.__name__}"
                ) from exc
        if resp.status_code == 401:
            raise ErpNextAuthError("ERPNext refused the API key and secret.")
        if resp.status_code == 403:
            what = path.removeprefix("/api/resource/").removeprefix("/api/method/")
            raise ErpNextError(f"ERPNext doesn't let this API user read or change {what}.")
        if resp.status_code >= 400:
            raise ErpNextError(f"ERPNext: {_message(resp)}")
        return resp.json()

    # --- reads -------------------------------------------------------------------------

    async def whoami(self) -> str:
        user: str = (await self._send("GET", "/api/method/frappe.auth.get_logged_user"))["message"]
        return user

    async def rows(
        self,
        doctype: str,
        fields: Iterable[str],
        filters: list[list[Any]] | None = None,
        order_by: str = "name asc",
    ) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        start = 0
        while True:
            params = {
                "fields": json.dumps(list(fields)),
                "filters": json.dumps(filters or []),
                "order_by": order_by,
                "limit_start": start,
                "limit_page_length": PAGE,
            }
            page = (await self._send("GET", f"/api/resource/{doctype}", params=params))["data"]
            rows.extend(page)
            if len(page) < PAGE:
                return rows
            start += PAGE

    async def get(self, doctype: str, name: str) -> dict[str, Any]:
        doc: dict[str, Any] = (await self._send("GET", _doc_path(doctype, name)))["data"]
        return doc

    async def get_many(self, doctype: str, names: Iterable[str]) -> list[dict[str, Any]]:
        """Whole documents (with their child tables), a few at a time."""
        return list(await asyncio.gather(*(self.get(doctype, n) for n in names)))

    async def find_by_ref(self, doctype: str, ref: str) -> dict[str, Any] | None:
        rows = await self.rows(doctype, ["name", "docstatus"], [[REF_FIELD, "=", ref]])
        return rows[0] if rows else None

    # --- writes (only from an approved posting task) -----------------------------------

    async def insert(self, doc: dict[str, Any]) -> dict[str, Any]:
        out: dict[str, Any] = (
            await self._send("POST", f"/api/resource/{doc['doctype']}", json=doc)
        )["data"]
        return out

    async def submit(self, doctype: str, name: str) -> dict[str, Any]:
        out: dict[str, Any] = (
            await self._send("PUT", _doc_path(doctype, name), json={"docstatus": 1})
        )["data"]
        return out


def api(creds: Credentials) -> Api:
    return Api(creds)
