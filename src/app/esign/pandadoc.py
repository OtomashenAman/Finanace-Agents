"""PandaDoc's public API: create a document from a file, send it, read its status, download.

https://developers.pandadoc.com/reference — a document uploaded from a file is processed for
a few seconds (document.uploaded) and can only be sent once it is document.draft.
"""

import json
from dataclasses import dataclass
from typing import Any

import httpx

from src.app.core.config import get_settings
from src.app.esign.exceptions import PandaDocError, PandaDocNotConfiguredError


@dataclass(frozen=True)
class Signer:
    email: str
    first_name: str
    last_name: str
    role: str  # matches the role in the file's field tags, e.g. {signature:signer1___}
    # Lower signs first; the same number: in parallel. None for everyone: no order
    signing_order: int | None = None


# Tests swap this for an httpx.MockTransport: no request ever leaves a test
transport: httpx.AsyncBaseTransport | None = None


def _message(resp: httpx.Response) -> str:
    try:
        body = resp.json()
    except ValueError:
        return resp.text[:300] or f"HTTP {resp.status_code}"
    if isinstance(body, dict):
        detail = body.get("detail") or body.get("message") or body.get("type")
        if isinstance(detail, dict):  # {"detail": {"field": ["problem"]}}
            detail = "; ".join(f"{k}: {v}" for k, v in detail.items())
        if detail:
            return str(detail)[:300]
    return resp.text[:300]


class PandaDoc:
    def __init__(self, api_key: str, base_url: str, timeout: float) -> None:
        self._headers = {"Authorization": f"API-Key {api_key}", "Accept": "application/json"}
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout

    def _client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            base_url=self._base_url,
            headers=self._headers,
            timeout=self._timeout,
            transport=transport,
        )

    async def _call(self, method: str, path: str, **kwargs: Any) -> httpx.Response:
        try:
            async with self._client() as client:
                resp = await client.request(method, path, **kwargs)
        except httpx.TimeoutException as exc:
            raise PandaDocError("PandaDoc didn't answer in time. Try again.") from exc
        except httpx.HTTPError as exc:
            raise PandaDocError(f"PandaDoc can't be reached: {exc}") from exc
        if resp.status_code in (401, 403) and "download-protected" not in path:
            raise PandaDocError(
                "PandaDoc refused the API key (or the account is out of API credits)."
            )
        return resp

    async def _json(self, method: str, path: str, **kwargs: Any) -> dict[str, Any]:
        resp = await self._call(method, path, **kwargs)
        if resp.status_code >= 400:
            raise PandaDocError(f"PandaDoc: {_message(resp)}", status=resp.status_code)
        body: dict[str, Any] = resp.json() if resp.content else {}
        return body

    async def create_from_file(
        self,
        name: str,
        filename: str,
        content_type: str,
        data: bytes,
        signers: list[Signer],
        fields: dict[str, dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        """Upload the file as a new document (document.uploaded). Field tags in the file
        ({signature:signer1___}) become the signers' fields."""
        payload = {
            "name": name,
            "recipients": [
                {
                    "email": s.email,
                    "first_name": s.first_name,
                    "last_name": s.last_name,
                    "role": s.role,
                    **({"signing_order": s.signing_order} if s.signing_order else {}),
                }
                for s in signers
            ],
            "parse_form_fields": False,
        }
        if fields:  # {tag id: {"value", "role"}}: the dynamic fields, filled in
            payload["fields"] = fields
        return await self._json(
            "POST",
            "/public/v1/documents",
            files={"file": (filename, data, content_type)},
            data={"data": json.dumps(payload)},
        )

    async def status(self, document_id: str) -> dict[str, Any]:
        return await self._json("GET", f"/public/v1/documents/{document_id}")

    async def details(self, document_id: str) -> dict[str, Any]:
        """Status, recipients (has_completed) and dates."""
        return await self._json("GET", f"/public/v1/documents/{document_id}/details")

    async def add_signature_boxes(
        self, document_id: str, boxes: list[tuple[str, dict[str, float]]]
    ) -> None:
        """One signature field per (recipient id, layout) on a draft document."""
        fields = [
            {
                "type": "signature",
                "assigned_to": recipient_id,
                "settings": {"required": True},
                "layout": {
                    "page": int(box["page"]),
                    "position": {
                        "offset_x": box["x"],
                        "offset_y": box["y"],
                        "anchor_point": "topleft",
                    },
                    "style": {"width": box["width"], "height": box["height"]},
                },
            }
            for recipient_id, box in boxes
        ]
        await self._json(
            "POST", f"/public/v1/documents/{document_id}/fields", json={"fields": fields}
        )

    async def signing_session(self, document_id: str, email: str, lifetime: int) -> str:
        """A session for `email` to sign inside the app (https://app.pandadoc.com/s/{id}/)."""
        result = await self._json(
            "POST",
            f"/public/v1/documents/{document_id}/session",
            json={"recipient": email, "lifetime": lifetime},
        )
        return str(result["id"])

    async def send(self, document_id: str, subject: str | None, message: str | None) -> str:
        body: dict[str, Any] = {"silent": False}
        if subject:
            body["subject"] = subject
        if message:
            body["message"] = message
        result = await self._json("POST", f"/public/v1/documents/{document_id}/send", json=body)
        return str(result.get("status") or "document.sent")

    async def download(self, document_id: str, completed: bool) -> bytes:
        """The PDF. A completed one comes from the e-vault (with its certificate), which only
        a production key can read: a sandbox key falls back to the plain download."""
        if completed:
            resp = await self._call("GET", f"/public/v1/documents/{document_id}/download-protected")
            if resp.status_code == 200:
                return resp.content
        resp = await self._call("GET", f"/public/v1/documents/{document_id}/download")
        if resp.status_code != 200:
            raise PandaDocError(f"PandaDoc: {_message(resp)}", status=resp.status_code)
        return resp.content


def client() -> PandaDoc:
    settings = get_settings()
    if settings.pandadoc_api_key is None:
        raise PandaDocNotConfiguredError()
    return PandaDoc(
        settings.pandadoc_api_key.get_secret_value(),
        settings.pandadoc_api_url,
        settings.pandadoc_timeout_seconds,
    )
