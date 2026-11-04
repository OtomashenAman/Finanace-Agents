"""Microsoft Graph for one Microsoft 365 mailbox: an app-only token (client credentials of an
Entra app registration), sending as the mailbox (Mail.Send) and reading its inbox for
customer replies (Mail.Read). Nothing else in the tenant is touched."""

import time
from dataclasses import dataclass
from datetime import datetime
from typing import Any

import httpx

from src.app.core.config import get_settings

GRAPH = "https://graph.microsoft.com/v1.0"
LOGIN = "https://login.microsoftonline.com"

# (tenant, client id) -> (token, expiry as wall-clock epoch seconds); a token lasts about an hour.
# Wall clock, not time.monotonic(): on Linux (WSL, Docker) the monotonic clock stops while the
# machine sleeps, so after a sleep an expired token would still look fresh (Graph: 401 "Invalid
# token lifetime")
_tokens: dict[tuple[str, str], tuple[str, float]] = {}


class GraphError(Exception):
    """Microsoft refused the request or couldn't be reached."""

    def __init__(self, message: str, *, status: int | None = None, uncertain: bool = False):
        super().__init__(message)
        self.status = status
        self.uncertain = uncertain  # a timeout / 5xx: the request may still have taken effect


@dataclass(frozen=True)
class InboxItem:
    id: str
    sender: str  # lower case
    received_at: datetime


class GraphMailbox:
    def __init__(
        self,
        tenant_id: str,
        client_id: str,
        client_secret: str,
        mailbox: str,
        timeout: float,
        transport: httpx.AsyncBaseTransport | None = None,  # tests
    ) -> None:
        self.mailbox = mailbox
        self._tenant, self._client_id, self._secret = tenant_id, client_id, client_secret
        self._timeout = timeout
        self._transport = transport

    @classmethod
    def from_settings(cls) -> "GraphMailbox":
        s = get_settings()
        assert s.ms_tenant_id and s.ms_client_id and s.ms_client_secret and s.ms_mailbox  # noqa: S101 - config validated
        return cls(
            s.ms_tenant_id,
            s.ms_client_id,
            s.ms_client_secret.get_secret_value(),
            s.ms_mailbox,
            s.email_timeout_seconds,
        )

    def _http(self, base_url: str) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            base_url=base_url, timeout=self._timeout, transport=self._transport
        )

    async def token(self) -> str:
        key = (self._tenant, self._client_id)
        cached = _tokens.get(key)
        if cached and cached[1] > time.time() + 60:
            return cached[0]
        try:
            async with self._http(LOGIN) as client:
                resp = await client.post(
                    f"/{self._tenant}/oauth2/v2.0/token",
                    data={
                        "grant_type": "client_credentials",
                        "client_id": self._client_id,
                        "client_secret": self._secret,
                        "scope": "https://graph.microsoft.com/.default",
                    },
                )
        except httpx.HTTPError as exc:
            raise GraphError(f"Microsoft sign-in can't be reached: {exc}") from exc
        if resp.status_code != 200:
            detail = resp.json().get("error_description", "") if resp.content else ""
            raise GraphError(
                f"Microsoft refused the app's credentials ({resp.status_code}): "
                f"{detail.splitlines()[0] if detail else 'check the tenant, client ID and secret'}",
                status=resp.status_code,
            )
        body = resp.json()
        _tokens[key] = (body["access_token"], time.time() + int(body.get("expires_in", 3599)))
        return str(body["access_token"])

    async def request(self, method: str, path: str, **kwargs: Any) -> httpx.Response:
        """A Graph call on this mailbox (`path` after /users/<mailbox>)."""
        resp = await self._send(method, path, **kwargs)
        if resp.status_code == 401:
            # The cached token was rejected (expired or revoked): one retry with a fresh one.
            # A 401 means the request wasn't carried out, so resending it is safe
            _tokens.pop((self._tenant, self._client_id), None)
            resp = await self._send(method, path, **kwargs)
        if resp.status_code >= 400:
            try:
                detail = resp.json()["error"]["message"]
            except (ValueError, KeyError, TypeError):
                detail = resp.text[:300]
            raise GraphError(
                f"Microsoft Graph answered {resp.status_code}: {detail}",
                status=resp.status_code,
                uncertain=resp.status_code >= 500,
            )
        return resp

    async def _send(self, method: str, path: str, **kwargs: Any) -> httpx.Response:
        headers = {"Authorization": f"Bearer {await self.token()}"}
        try:
            async with self._http(GRAPH) as client:
                return await client.request(
                    method, f"/users/{self.mailbox}{path}", headers=headers, **kwargs
                )
        except httpx.TimeoutException as exc:
            raise GraphError("Microsoft Graph didn't answer in time.", uncertain=True) from exc
        except httpx.HTTPError as exc:
            raise GraphError(
                f"Network error talking to Microsoft Graph: {exc}", uncertain=True
            ) from exc

    async def inbox_since(self, since: datetime, limit: int = 50) -> list[InboxItem]:
        """Inbox messages received after `since`, oldest first."""
        resp = await self.request(
            "GET",
            "/mailFolders/inbox/messages",
            params={
                "$filter": f"receivedDateTime gt {since.strftime('%Y-%m-%dT%H:%M:%SZ')}",
                "$orderby": "receivedDateTime asc",
                "$select": "id,from,receivedDateTime",
                "$top": str(limit),
            },
        )
        items = []
        for m in resp.json().get("value", []):
            address = ((m.get("from") or {}).get("emailAddress") or {}).get("address") or ""
            items.append(
                InboxItem(
                    id=m["id"],
                    sender=address.strip().lower(),
                    received_at=datetime.fromisoformat(
                        m["receivedDateTime"].replace("Z", "+00:00")
                    ),
                )
            )
        return items

    async def mime(self, message_id: str) -> str:
        """The message as the original email file (headers prove the thread)."""
        resp = await self.request("GET", f"/messages/{message_id}/$value")
        return resp.content.decode("utf-8", errors="replace")
