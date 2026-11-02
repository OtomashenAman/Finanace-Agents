"""Finance POD fixtures: people with capacities, and a small demo workflow with steps.

The demo workflow stands in for the real ones while the engine is tested: it borrows an
existing workflow key for the test's duration (so the database's key constraint holds) and
puts the Finance POD spec and no hooks in its place.
"""

from collections.abc import Callable, Iterator
from decimal import Decimal
from typing import Any

import httpx
import pytest
from httpx import AsyncClient
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.auth.models import User, UserRole
from src.app.data_sources import crypto
from src.app.data_sources.models import DataSource, IntegrationEnvironment, SourceKind, SourceStatus
from src.app.data_sources.providers import erpnext as provider
from src.app.entities.models import LegalEntity
from src.app.finance_pod.capacities import FinanceCapacity
from src.app.finance_pod.models import FinanceCapacityAssignment
from src.app.service_pod.core.cases.models import PodCase
from src.app.service_pod.core.hooks import HOOKS
from src.app.service_pod.core.steps.spec import (
    OWNER,
    L5Spec,
    Measure,
    Rule,
    StepFailedError,
    StepKind,
    StepPlan,
    StepResult,
    StepSpec,
)
from src.app.service_pod.core.workflows import WORKFLOWS, PodKey, WorkflowKey, WorkflowSpec
from tests.conftest import ClientFactory, MakeUser
from tests.finance_pod.fake_erpnext import COMPANY, KEY, SECRET, FakeErpNext
from tests.service_pod.conftest import import_snapshot

DEMO_KEY = WorkflowKey.TREASURY  # borrowed for the test's duration (see the module doc)
Cap = FinanceCapacity


class DescribeResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    item: str = Field(min_length=1, max_length=200)
    quantity: int = Field(gt=0)


class AgentSwitch:
    """Lets a test make the demo agent fail."""

    fail: str | None = None


AGENT = AgentSwitch()


async def _budget_agent(c: Any, step: StepSpec) -> dict[str, BaseModel]:
    if AGENT.fail:
        raise StepFailedError(AGENT.fail)
    return {"1.2.a": StepResult(note=f"checked {c.case.selection.get('amount')}")}


async def _small_request(c: Any) -> str | None:
    amount = Decimal(str(c.case.selection.get("amount", 0)))
    return "Below the quote threshold (100)" if amount < 100 else None


async def _quantity_rule(c: Any) -> str | None:
    rows = [r for r in c.children.steps if r.l5_code == "1.1.a" and r.result]
    if rows and rows[0].result["quantity"] > 1000:
        return "Quantities above 1000 need a framework contract."
    return None


async def _count(session: AsyncSession, cases: list[PodCase]) -> Decimal | None:
    return Decimal(len(cases)) if cases else None


DEMO_SPEC = WorkflowSpec(
    key=DEMO_KEY,
    name="Demo purchase",
    prefix="DEMO",
    description="A test workflow with steps.",
    required=frozenset(),
    signoffs=(Cap.BUDGET_OWNER.value,),
    pod=PodKey.FINANCE,
    signoff_sod=True,
    plan=StepPlan(
        steps=(
            StepSpec("1.1", "1.1", "Describe the need", StepKind.PERSON,
                     (L5Spec("1.1.a", "Item and quantity", DescribeResult),),
                     capacity=Cap.REQUESTER.value),
            StepSpec("1.2", "1.2", "Budget agent checks", StepKind.AGENT,
                     (L5Spec("1.2.a", "Remaining budget"),),
                     after=("1.1",), handler=_budget_agent),
            StepSpec("1.3", "1.3", "Budget owner decides", StepKind.PERSON,
                     (L5Spec("1.3.a", "Approves, rejects or queries"),),
                     capacity=Cap.BUDGET_OWNER.value, after=("1.2",),
                     distinct_from=(OWNER, "1.1")),
            StepSpec("1.4", "1.4", "Buyer gets quotes", StepKind.PERSON,
                     (L5Spec("1.4.a", "Quotes above threshold"),),
                     capacity=Cap.BUYER.value, after=("1.3",),
                     not_applicable_when=_small_request),
        ),
        rules=(Rule("DEMO.R1", "Quantities above 1000 need a contract", check=_quantity_rule),),
        measures=(Measure("DEMO.M1", "Cases", "count", _count),),
        viewers=frozenset({Cap.BUDGET_OWNER.value, Cap.BUYER.value}),
        openers=frozenset({Cap.REQUESTER.value}),
    ),
)  # fmt: skip


@pytest.fixture
def demo_flow(monkeypatch: pytest.MonkeyPatch) -> Iterator[WorkflowSpec]:
    monkeypatch.setitem(WORKFLOWS, DEMO_KEY, DEMO_SPEC)
    if DEMO_KEY in HOOKS:
        monkeypatch.delitem(HOOKS, DEMO_KEY)
    AGENT.fail = None
    yield DEMO_SPEC
    AGENT.fail = None


@pytest.fixture
async def entity(db: AsyncSession) -> LegalEntity:
    e = LegalEntity(code="US01", name="US Operations")
    db.add(e)
    await db.commit()
    return e


@pytest.fixture
async def admin_user(make_user: MakeUser) -> User:
    return await make_user("fa@example.com", UserRole.FINANCE_ADMIN)


@pytest.fixture
async def admin(admin_user: User, signed_in_client: ClientFactory) -> AsyncClient:
    return await signed_in_client(admin_user)


GrantFn = Callable[..., Any]


@pytest.fixture
def grant(db: AsyncSession) -> GrantFn:
    async def _grant(user: User, *capacities: Cap, entity: LegalEntity | None = None) -> None:
        for capacity in capacities:
            db.add(
                FinanceCapacityAssignment(
                    user_id=user.id, capacity=capacity, entity_id=entity.id if entity else None
                )
            )
        await db.commit()

    return _grant


PersonFn = Callable[..., Any]


@pytest.fixture
def person(make_user: MakeUser, signed_in_client: ClientFactory, grant: GrantFn) -> PersonFn:
    """`await person("req@example.com", Cap.REQUESTER)` -> (user, signed-in client)."""

    async def _person(
        email: str, *capacities: Cap, entity: LegalEntity | None = None
    ) -> tuple[User, AsyncClient]:
        user = await make_user(email)
        await grant(user, *capacities, entity=entity)
        return user, await signed_in_client(user)

    return _person


@pytest.fixture
async def snapshot(admin: AsyncClient, entity: LegalEntity) -> dict[str, Any]:
    r = await import_snapshot(admin, entity)
    assert r.status_code == 201, r.text
    snap: dict[str, Any] = r.json()["snapshot"]
    return snap


async def open_demo(
    client: AsyncClient, snapshot: dict[str, Any], amount: int = 50, title: str = "Pipettes"
) -> Any:
    return await client.post(
        "/api/v1/finance/cases",
        json={
            "workflow": DEMO_KEY.value,
            "snapshot_id": snapshot["id"],
            "title": title,
            "selection": {"amount": amount},
        },
    )


async def act(client: AsyncClient, case: dict[str, Any], action: str, **payload: Any) -> Any:
    return await client.post(
        f"/api/v1/finance/cases/{case['id']}/actions",
        json={"action": action, "expected_version": case["version"], "payload": payload},
    )


def step(case: dict[str, Any], key: str) -> dict[str, Any]:
    found: dict[str, Any] = next(s for s in case["steps"] if s["key"] == key)
    return found


# --- the AP world: people with each capacity, and an ERPNext connection (a stand-in) ---


@pytest.fixture
def erp(monkeypatch: pytest.MonkeyPatch) -> Iterator[FakeErpNext]:
    fake = FakeErpNext()
    monkeypatch.setattr(provider, "transport", httpx.MockTransport(fake.handler))
    yield fake


class World:
    def __init__(self) -> None:
        self.users: dict[str, User] = {}
        self.clients: dict[str, AsyncClient] = {}
        self.source: DataSource | None = None
        self.admin: AsyncClient | None = None
        self.entity: LegalEntity | None = None

    def __getitem__(self, who: str) -> AsyncClient:
        return self.clients[who]


@pytest.fixture
async def world(
    admin: AsyncClient,
    admin_user: User,
    entity: LegalEntity,
    person: PersonFn,
    db: AsyncSession,
    erp: FakeErpNext,
) -> World:
    w = World()
    w.admin, w.entity = admin, entity
    for who, caps in (
        ("req", (Cap.REQUESTER,)),
        ("bo", (Cap.BUDGET_OWNER,)),
        ("buyer", (Cap.BUYER,)),
        ("analyst", (Cap.AP_ANALYST,)),
        ("approver", (Cap.VENDOR_APPROVER,)),
    ):
        w.users[who], w.clients[who] = await person(f"{who}@example.com", *caps)
    w.source = DataSource(
        owner_id=admin_user.id,
        kind=SourceKind.ERPNEXT,
        name="ERPNext",
        status=SourceStatus.CONNECTED,
        base_url="http://erp.example.test",
        client_id=KEY,
        client_secret_enc=crypto.encrypt(SECRET),
        external_id=COMPANY,
        environment=IntegrationEnvironment.SANDBOX,
        record_counts={},
    )
    db.add(w.source)
    await db.commit()
    return w
