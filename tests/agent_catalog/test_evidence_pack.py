import hashlib
import io
import json
import zipfile

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.agent_catalog.models import AgentCapacity
from src.app.audit.models import AuditEvent
from src.app.auth.models import User, UserRole
from tests.agent_catalog.test_runs_api import RUNS, act, analyzed_run, assign, upload
from tests.common.test_text_extraction import make_pdf
from tests.conftest import ClientFactory, FakeLLM, MakeUser

pytestmark = pytest.mark.usefixtures("synced_agents")


async def test_evidence_pack_has_everything_with_hashes(
    prep: AsyncClient,
    make_user: MakeUser,
    signed_in_client: ClientFactory,
    db: AsyncSession,
    fake_llm: FakeLLM,
) -> None:
    run = await analyzed_run(prep)
    run = (
        await upload(prep, run, "invoice.pdf", make_pdf(["Invoice INV-2048 total 12500.00"]))
    ).json()
    run = await act(prep, await act(prep, run, "analyze"), "submit")
    admin = await signed_in_client(await make_user("admin@example.com", UserRole.FINANCE_ADMIN))
    await act(admin, run, "reviews", decision="approved", comment="Checked the receipt")

    r = await prep.get(f"{RUNS}/{run['id']}/evidence-pack")
    assert r.status_code == 200
    assert r.headers["content-type"] == "application/zip"
    assert f'filename="{run["reference"]}-evidence.zip"' in r.headers["content-disposition"]

    zf = zipfile.ZipFile(io.BytesIO(r.content))
    manifest = json.loads(zf.read("manifest.json"))
    names = {f["name"] for f in manifest["files"]}
    assert {"summary.txt", "run.json", "audit-trail.json", "documents/D1-invoice.pdf.txt"} <= names
    for f in manifest["files"]:
        assert hashlib.sha256(zf.read(f["name"])).hexdigest() == f["sha256"]
    doc = next(f for f in manifest["files"] if f["name"].startswith("documents/"))
    assert doc["source_sha256"] == run["documents"][0]["sha256"]
    assert manifest["result_hash"] == run["result_hash"]

    summary = zf.read("summary.txt").decode()
    assert "approved by Admin: Checked the receipt" in summary
    assert "Invoice INV-2048 total 12500.00" in zf.read("documents/D1-invoice.pdf.txt").decode()
    events = [e["event_type"] for e in json.loads(zf.read("audit-trail.json"))]
    assert events[:2] == ["run.created", "run.analyzed"] and "run.approved" in events

    exported = await db.scalar(
        select(AuditEvent).where(AuditEvent.event_type == "run.evidence_exported")
    )
    assert exported is not None
    assert exported.details["sha256"] == hashlib.sha256(r.content).hexdigest()

    # The admin can export it too; another user can't see the run at all
    assert (await admin.get(f"{RUNS}/{run['id']}/evidence-pack")).status_code == 200
    outsider = await signed_in_client(await make_user("x@example.com"))
    assert (await outsider.get(f"{RUNS}/{run['id']}/evidence-pack")).status_code == 404


@pytest.fixture
async def prep(
    make_user: MakeUser, db: AsyncSession, signed_in_client: ClientFactory
) -> AsyncClient:
    user: User = await make_user("ap.analyst@example.com")
    await assign(db, user, AgentCapacity.PREPARER)
    return await signed_in_client(user)
