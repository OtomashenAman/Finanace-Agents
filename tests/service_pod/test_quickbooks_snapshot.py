"""Freezing a QuickBooks Online connection's synced records into a snapshot."""

from datetime import date
from decimal import Decimal

from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.auth.models import User
from src.app.common.clock import utcnow
from src.app.data_sources.models import (
    DataSource,
    FinanceRecord,
    IntegrationEnvironment,
    SourceKind,
    SourceStatus,
)
from src.app.data_sources.records import Customer, Invoice, Payment, Record, RecordType
from src.app.entities.models import LegalEntity
from src.app.service_pod.core.snapshots.importers.quickbooks_online import _email


async def _connection(
    db: AsyncSession, owner: User, records: dict[RecordType, list[Record]]
) -> DataSource:
    source = DataSource(
        owner_id=owner.id,
        kind=SourceKind.QUICKBOOKS,
        name="Sandbox Company US",
        status=SourceStatus.CONNECTED,
        environment=IntegrationEnvironment.SANDBOX,
        external_id="9341",
        last_synced_at=utcnow(),
        record_counts={},
    )
    db.add(source)
    await db.flush()
    for record_type, items in records.items():
        db.add_all(
            FinanceRecord(
                source_id=source.id,
                record_type=record_type,
                external_id=r.external_id,
                reference=r.reference,
                counterparty=r.counterparty,
                amount=r.amount,
                txn_date=r.txn_date,
                data=r.model_dump(mode="json"),
            )
            for r in items
        )
    await db.commit()
    return source


def _invoice(n: str, total: str, balance: str, customer: str = "Amy's Bird Sanctuary") -> Invoice:
    return Invoice(
        external_id=f"i{n}",
        doc_number=n,
        customer_name=customer,
        total=Decimal(total),
        balance=Decimal(balance),
        invoice_date=date(2026, 9, 1),
        due_date=date(2026, 10, 1),
    )


async def test_zero_payments_are_left_out(
    pod: AsyncClient, admin_user: User, entity: LegalEntity, db: AsyncSession
) -> None:
    source = await _connection(
        db,
        admin_user,
        {
            RecordType.CUSTOMER: [
                Customer(
                    external_id="c1", name="Amy's Bird Sanctuary", email="birds@intuit.example"
                )
            ],
            RecordType.INVOICE: [
                _invoice("1037", "362.07", "362.07"),
                _invoice("1001", "108.00", "0"),
            ],
            RecordType.PAYMENT: [
                # a credit memo applied to an invoice: QuickBooks records it as a 0.00 payment
                Payment(
                    external_id="p0",
                    reference_number="CM-1",
                    customer_name="Amy's Bird Sanctuary",
                    total=Decimal("0.00"),
                    payment_date=date(2026, 9, 20),
                    invoice_number="1001",
                    applied_amount=Decimal("0.00"),
                ),
                Payment(
                    external_id="p1",
                    reference_number="CHK-55",
                    customer_name="Amy's Bird Sanctuary",
                    total=Decimal("108.00"),
                    payment_date=date(2026, 9, 25),
                    invoice_number="1001",
                    applied_amount=Decimal("108.00"),
                ),
            ],
        },
    )
    r = await pod.post(
        "/api/v1/pod/snapshots/quickbooks",
        json={
            "data_source_id": str(source.id),
            "entity_id": str(entity.id),
            "currency": "USD",
            "basis": "Accrual",
        },
    )
    assert r.status_code == 201, r.text
    snap = r.json()["snapshot"]
    assert snap["is_demo"] is True  # a sandbox company
    assert snap["row_counts"]["payments"] == 1


async def test_invoices_of_a_deleted_customer_are_kept(
    pod: AsyncClient, admin_user: User, entity: LegalEntity, db: AsyncSession
) -> None:
    # QuickBooks lists only active customers and renames a deleted one "<name> (deleted)"
    gone = "Kani Solutions Inc (deleted)"
    source = await _connection(
        db,
        admin_user,
        {
            RecordType.CUSTOMER: [
                # QuickBooks allows several addresses in one email field
                Customer(
                    external_id="c1",
                    name="Amy's Bird Sanctuary",
                    email="ap@birds.example,amy@birds.example",
                )
            ],
            RecordType.INVOICE: [
                _invoice("1037", "100.00", "100.00"),
                _invoice("2173301", "500.00", "500.00", gone),
                _invoice("2174294", "250.00", "250.00", gone),
            ],
            RecordType.PAYMENT: [
                Payment(
                    external_id="p1",
                    reference_number="CHK-9",
                    customer_name=gone,
                    total=Decimal("50.00"),
                    payment_date=date(2026, 9, 25),
                )
            ],
        },
    )
    r = await pod.post(
        "/api/v1/pod/snapshots/quickbooks",
        json={
            "data_source_id": str(source.id),
            "entity_id": str(entity.id),
            "currency": "USD",
            "basis": "Accrual",
        },
    )
    assert r.status_code == 201, r.text
    counts = r.json()["snapshot"]["row_counts"]
    assert counts["customers"] == 2 and counts["invoices"] == 3 and counts["payments"] == 1


def test_the_first_valid_address_is_the_contact() -> None:
    assert _email("ap@birds.example,amy@birds.example") == "ap@birds.example"
    assert _email("Amy; amy@birds.example") == "amy@birds.example"
    assert _email("call Amy") is None
    assert _email("amy@") is None
    assert _email(None) is None


async def test_a_bad_record_is_named_not_a_crash(
    pod: AsyncClient, admin_user: User, entity: LegalEntity, db: AsyncSession
) -> None:
    source = await _connection(
        db,
        admin_user,
        {
            RecordType.CUSTOMER: [Customer(external_id="c1", name="Amy's Bird Sanctuary")],
            # balance above the invoice amount: refused by the contract
            RecordType.INVOICE: [_invoice("1037", "100.00", "150.00")],
            RecordType.PAYMENT: [],
        },
    )
    r = await pod.post(
        "/api/v1/pod/snapshots/quickbooks",
        json={
            "data_source_id": str(source.id),
            "entity_id": str(entity.id),
            "currency": "USD",
            "basis": "Accrual",
        },
    )
    assert r.status_code == 422
    assert "invoice 1037" in r.json()["detail"]["message"]
