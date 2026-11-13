"""Finance POD demo data, loaded from the app (Setup) or the command line, on any database
including production. Each section is skipped when its data is already there, so loading
twice changes nothing. No email is sent.

People: the person loading it is the requester and buyer; another active Finance Admin (if
there is one) is the budget owner, senior buyer and second approver, so separation of
duties can be shown. With only one Finance Admin, turn on self-approval in Setup.
"""

import hashlib
import io
from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal
from typing import Any

from openpyxl import Workbook
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.audit.service import record_event
from src.app.auth.models import User
from src.app.common.clock import utcnow
from src.app.common.context import RequestContext
from src.app.core.errors import AppError
from src.app.data_sources import crypto
from src.app.finance_pod import pdf
from src.app.finance_pod.access import finance_pod_people
from src.app.finance_pod.billing import service as billing
from src.app.finance_pod.billing import workbook as fee_workbook
from src.app.finance_pod.billing.models import FpFee, SalesInvoiceStatus
from src.app.finance_pod.billing.schemas import PerformedIn, SubmissionIn
from src.app.finance_pod.clients import agents as client_agents
from src.app.finance_pod.clients.models import (
    ApplicationStatus,
    ClientDocumentKind,
    ClientStatus,
    FpClient,
    FpClientApplication,
    FpClientDocument,
    FpClientHistory,
)
from src.app.finance_pod.clients.service import push
from src.app.finance_pod.invoices.models import FpInvoice, FpReceipt, FpReceiptLine, InvoiceStatus
from src.app.finance_pod.onboarding import sanctions
from src.app.finance_pod.onboarding.models import (
    FpOnboarding,
    FpVendorBankAccount,
    OnboardingKind,
    OnboardingStatus,
)
from src.app.finance_pod.orders.models import FpPoLine, FpPurchaseOrder, PoStatus
from src.app.finance_pod.reference import service as reference
from src.app.finance_pod.reference.models import (
    FpAuthorityTier,
    FpBudget,
    FpCatalogueItem,
    FpCostCentre,
    FpGrant,
    FpLab,
    FpProject,
    FpVendor,
)
from src.app.finance_pod.requests.models import FpPurchaseRequest, FpRequestLine, RequestStatus
from src.app.finance_pod.settings.service import current


@dataclass
class DemoResult:
    loaded: list[str] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)


@dataclass
class People:
    me: User
    owner: User  # budget owner, senior buyer, second approver
    dean: User

    @property
    def alone(self) -> bool:
        return self.owner.id == self.me.id


async def _people(session: AsyncSession, me: User) -> People:
    others = list(
        await session.scalars(
            select(User).where(finance_pod_people(), User.id != me.id).order_by(User.created_at)
        )
    )
    owner = others[0] if others else me
    return People(me=me, owner=owner, dean=others[1] if len(others) > 1 else owner)


def _workbook(sheets: dict[str, list[list[Any]]]) -> bytes:
    book = Workbook()
    book.remove(book.active)  # type: ignore[arg-type]
    for title, rows in sheets.items():
        ws = book.create_sheet(title)
        for row in rows:
            ws.append(row)
    buffer = io.BytesIO()
    book.save(buffer)
    return buffer.getvalue()


VENDORS = [
    (
        "V-FISH",
        "Lab Supply Co",
        "labsupply.gia@yopmail.com",
        "12-3456789",
        "lab supplies",
        "Chase",
        140,
    ),
    (
        "V-CHEM",
        "ChemSource Ltd",
        "chemsource.gia@yopmail.com",
        "23-4567890",
        "chemicals",
        "Bank of America",
        120,
    ),
    (
        "V-SEQ",
        "GenServ Instruments",
        "genserv.gia@yopmail.com",
        "34-5678901",
        "equipment service",
        "Wells Fargo",
        160,
    ),
    (
        "V-HELIX",
        "Helix Genomics Services",
        "helix.gia@yopmail.com",
        "45-6789012",
        "sequencing services",
        "Garden State Bank",
        6,
    ),
]


# Sheets matched on a code column: rows whose code is already there are left out
_CODED: dict[str, tuple[type[Any], str]] = {
    "Cost centres": (FpCostCentre, "code"),
    "Labs": (FpLab, "code"),
    "Projects": (FpProject, "code"),
    "Grants": (FpGrant, "code"),
    "Catalogue": (FpCatalogueItem, "item_code"),
    "Vendors": (FpVendor, "code"),
}


async def _missing(
    session: AsyncSession, sheets: dict[str, list[list[Any]]]
) -> dict[str, list[list[Any]]]:
    """The demo rows not there yet (someone may have loaded their own data, or the template's
    example rows), so what is there is never overwritten. Sheets with nothing new are left out."""
    out: dict[str, list[list[Any]]] = {}
    for title, (header, *rows) in sheets.items():
        if title in _CODED:
            model, column = _CODED[title]
            have = set(await session.scalars(select(getattr(model, column))))
            rows = [r for r in rows if r[0] not in have]
        elif title == "Budgets":
            have_keys = {
                (b.fiscal_year, b.cost_centre_code, b.grant_code, b.category)
                for b in await session.scalars(select(FpBudget))
            }
            rows = [r for r in rows if tuple(r[:4]) not in have_keys]
        elif await session.scalar(select(FpAuthorityTier.id).limit(1)):
            rows = []  # an import replaces the whole matrix: keep the one there
        if rows:
            out[title] = [header, *rows]
    return out


async def _reference(
    session: AsyncSession, p: People, ctx: RequestContext, out: DemoResult
) -> None:
    today = utcnow().date()
    owner, dean = p.owner.email, p.dean.email
    sheets: dict[str, list[list[Any]]] = {
        "Cost centres": [
            ["Code", "Name", "Owner Email", "Active"],
            ["CC-100", "Biology Department", owner, "yes"],
            ["CC-200", "Chemistry Department", owner, "yes"],
            ["CC-300", "Central IT", owner, "yes"],
        ],
        "Labs": [
            ["Code", "Name", "Cost Centre"],
            ["LAB-GEN", "Genomics Lab", "CC-100"],
            ["LAB-ORG", "Organic Synthesis Lab", "CC-200"],
        ],
        "Projects": [
            ["Code", "Name", "Cost Centre", "Grant"],
            ["PRJ-7", "Sequencing study", "CC-100", "GR-22"],
        ],
        "Grants": [
            [
                "Code",
                "Name",
                "Sponsor",
                "Cost Centre",
                "Start Date",
                "End Date",
                "Award Amount",
                "Unallowable Categories",
            ],
            [
                "GR-22",
                "Genome sequencing programme",
                "NSF",
                "CC-100",
                (today - timedelta(days=365)).isoformat(),
                (today + timedelta(days=365)).isoformat(),
                250000,
                "alcohol; entertainment",
            ],
        ],
        "Budgets": [
            ["Fiscal Year", "Cost Centre", "Grant", "Category", "Amount", "Committed", "Spent"],
            [today.year, "CC-100", None, None, 120000, 10000, 45000],
            [today.year, "CC-200", None, None, 80000, 5000, 31000],
            [today.year, None, "GR-22", "lab supplies", 80000, 0, 12000],
        ],
        "Catalogue": [
            [
                "Item Code",
                "Description",
                "Category",
                "Unit",
                "Unit Price",
                "Vendor",
                "Contract Ref",
            ],
            [
                "PIP-200",
                "Pipette tips 200ul, box of 960",
                "lab supplies",
                "box",
                42.50,
                "V-FISH",
                "CT-2026-01",
            ],
            [
                "GLV-M",
                "Nitrile gloves medium, box of 100",
                "lab supplies",
                "box",
                9.00,
                "V-FISH",
                "CT-2026-01",
            ],
            [
                "TUBE-15",
                "15ml centrifuge tubes, case of 500",
                "lab supplies",
                "case",
                68.00,
                "V-FISH",
                "CT-2026-01",
            ],
            ["ETH-4L", "Ethanol absolute 4L", "chemicals", "bottle", 55.00, "V-CHEM", "CT-2026-04"],
        ],
        "Vendors": [["Code", "Name", "Email", "Tax ID", "Status", "Categories"]]
        + [[c, n, e, t, "approved", cat] for c, n, e, t, cat, _, _ in VENDORS],
        "Authority matrix": [
            ["Scope", "Cost Centre", "Min Amount", "Approver Email", "Capacity"],
            ["request", None, 0, owner, "Budget owner"],
            ["request", None, 25000, dean, "Dean of Research"],
            ["po", None, 15000, owner, "Senior buyer"],
        ],
    }
    missing = await _missing(session, sheets)
    if not missing:
        out.skipped.append("Reference data (cost centres, grants, budgets, catalogue, vendors)")
        return
    await reference.import_workbook(session, _workbook(missing), 10000, p.me, ctx)
    if missing == sheets:
        out.loaded.append(
            "Reference data: 3 cost centres, grant GR-22, budgets, 4 catalogue items, 4 vendors, "
            "authority matrix"
        )
    else:
        out.loaded.append(
            "Reference data the demo needs that wasn't there yet: "
            + ", ".join(f"{t.lower()} ({len(rows) - 1})" for t, rows in missing.items())
        )


async def _bank_accounts(session: AsyncSession, p: People, out: DemoResult) -> None:
    if await session.scalar(
        select(FpVendorBankAccount.id).where(FpVendorBankAccount.vendor_code == "V-FISH")
    ):
        out.skipped.append("Vendor bank accounts")
        return
    now = utcnow()
    for code, name, email, tax_id, _, bank, days in VENDORS:
        ob = FpOnboarding(
            kind=OnboardingKind.NEW_VENDOR,
            status=OnboardingStatus.ACTIVE,
            vendor_name=name,
            vendor_email=email,
            vendor_code=code,
            invited_by=p.me.id,
            legal_name=name,
            tax_id=tax_id,
            tax_form="W-9",
            bank_name=bank,
            account_name=name,
            account_last4=f"{4100 + days:04d}"[-4:],
            verified_by=p.me.id,
            verified_at=now - timedelta(days=days),
            activated_by=p.owner.id,
            activated_at=now - timedelta(days=days),
            erp_ref=code,
        )
        session.add(ob)
        await session.flush()
        session.add(
            FpVendorBankAccount(
                vendor_code=code,
                onboarding_id=ob.id,
                bank_name=bank,
                account_name=name,
                routing_number_enc=crypto.encrypt("021000021"),
                account_number_enc=crypto.encrypt(f"55500{4100 + days:04d}"),
                account_last4=f"{4100 + days:04d}"[-4:],
                created_at=now - timedelta(days=days),
            )
        )
    out.loaded.append(
        "Bank accounts for the 4 vendors (Helix's changed 6 days ago: a call-back flag)"
    )


PoLines = list[tuple[str | None, str, int, str]]  # catalogue code, description, qty, price
PURCHASES: list[tuple[str, str, str, str | None, str, PoLines, Decimal | int]] = [
    # title, vendor, cost centre, grant, terms, lines, share received
    (
        "Pipette tips and gloves for the sequencing run",
        "V-FISH",
        "CC-100",
        "GR-22",
        "2/10 Net 30",
        [
            ("PIP-200", "Pipette tips 200ul, box of 960", 20, "42.50"),
            ("GLV-M", "Nitrile gloves medium, box of 100", 30, "9.00"),
        ],
        1,
    ),
    (
        "Ethanol for the organic synthesis lab",
        "V-CHEM",
        "CC-200",
        None,
        "Net 30",
        [("ETH-4L", "Ethanol absolute 4L", 12, "55.00")],
        Decimal("0.5"),
    ),
    (
        "Sequencer annual service visit",
        "V-SEQ",
        "CC-100",
        "GR-22",
        "Net 30",
        [(None, "Sequencer preventive maintenance visit", 1, "4800.00")],
        0,
    ),
]


async def _purchasing(session: AsyncSession, p: People, out: DemoResult) -> None:
    if await session.scalar(
        select(FpPurchaseRequest.id).where(FpPurchaseRequest.title == PURCHASES[0][0])
    ):
        out.skipped.append("Purchase requests and POs")
        return
    now = utcnow()
    vendors = {v.code: v for v in await session.scalars(select(FpVendor))}
    for i, (title, vcode, cc, grant, terms, lines, received) in enumerate(PURCHASES):
        when = now - timedelta(days=20 - i * 4)
        req = FpPurchaseRequest(
            requester_id=p.me.id,
            status=RequestStatus.APPROVED,
            title=title,
            purpose=title,
            needed_by=(now + timedelta(days=21)).date(),
            currency="USD",
            cost_centre_code=cc,
            grant_code=grant,
            round=1,
            submitted_at=when,
            approved_at=when + timedelta(hours=3),
        )
        for n, (item, desc, qty, price) in enumerate(lines, 1):
            req.lines.append(
                FpRequestLine(
                    position=n,
                    description=desc,
                    quantity=Decimal(qty),
                    unit="each",
                    unit_price=Decimal(price),
                    catalogue_item_code=item,
                )
            )
        session.add(req)
        await session.flush()
        vendor = vendors[vcode]
        po = FpPurchaseOrder(
            request_id=req.id,
            status=PoStatus.ACKNOWLEDGED if received else PoStatus.ISSUED,
            vendor_code=vcode,
            vendor_name=vendor.name,
            vendor_email=vendor.email,
            currency="USD",
            payment_terms=terms,
            delivery_date=(when + timedelta(days=10)).date(),
            cost_centre_code=cc,
            grant_code=grant,
            drafted_by=p.me.id,
            issued_by=p.me.id,
            issued_at=when + timedelta(days=1),
            erp_system="local",
            acknowledged_at=when + timedelta(days=2) if received else None,
        )
        for n, (item, desc, qty, price) in enumerate(lines, 1):
            po.lines.append(
                FpPoLine(
                    position=n,
                    description=desc,
                    quantity=Decimal(qty),
                    unit="each",
                    unit_price=Decimal(price),
                    catalogue_item_code=item,
                    price_source="contract" if item else "quote",
                )
            )
        session.add(po)
        await session.flush()
        po.erp_ref = po.reference
        req.status, req.closed_at = RequestStatus.ORDERED, when + timedelta(days=1)
        if received:
            receipt = FpReceipt(
                po_id=po.id,
                received_on=(when + timedelta(days=8)).date(),
                receiver_email=p.me.email,
                recorded_by=p.me.id,
                via="app",
            )
            for n, (_, _, qty, _) in enumerate(lines, 1):
                receipt.lines.append(
                    FpReceiptLine(
                        po_line=n,
                        quantity=(Decimal(qty) * Decimal(received)).quantize(Decimal("1")),
                    )
                )
            session.add(receipt)
    # One waiting for the budget owner
    req = FpPurchaseRequest(
        requester_id=p.me.id,
        status=RequestStatus.SUBMITTED,
        title="15ml centrifuge tubes for the genomics lab",
        purpose="Tubes for sample prep",
        needed_by=(now + timedelta(days=14)).date(),
        currency="USD",
        cost_centre_code="CC-100",
        grant_code="GR-22",
        round=1,
        submitted_at=now - timedelta(hours=5),
    )
    req.lines.append(
        FpRequestLine(
            position=1,
            description="15ml centrifuge tubes, case of 500",
            quantity=Decimal(6),
            unit="case",
            unit_price=Decimal("68.00"),
            catalogue_item_code="TUBE-15",
        )
    )
    session.add(req)
    out.loaded.append(
        "3 issued POs to bill against: Lab Supply (all received, 2/10 Net 30), ChemSource (half "
        "received), GenServ (nothing received yet); 1 request waiting for the budget owner"
    )


READY = [
    # vendor, invoice no, total, days until due, terms
    ("V-FISH", "LSC-8140", "1284.47", 3, "Net 30"),
    ("V-CHEM", "CS-22817", "4860.00", 25, "2/10 Net 30"),
    ("V-SEQ", "GSI-5521", "2150.00", -4, "Net 30"),
    ("V-HELIX", "HGS-2026-118", "32400.00", 5, "Net 30"),
    ("V-HELIX", "HGS-2026-121", "1750.00", 6, "Net 30"),
]


async def _ready_invoices(session: AsyncSession, p: People, out: DemoResult) -> None:
    if await session.scalar(
        select(FpInvoice.id).where(FpInvoice.vendor_invoice_number == "LSC-8140")
    ):
        out.skipped.append("Invoices ready to pay")
        return
    today, now = utcnow().date(), utcnow()
    names = {v.code: v.name for v in await session.scalars(select(FpVendor))}
    for vcode, number, total, due_in, terms in READY:
        amount = Decimal(total)
        inv = FpInvoice(
            status=InvoiceStatus.READY,
            vendor_code=vcode,
            vendor_name=names.get(vcode, vcode),
            vendor_invoice_number=number,
            invoice_date=today + timedelta(days=due_in - 30),
            due_date=today + timedelta(days=due_in),
            currency="USD",
            total=amount,
            extraction={"payment_terms": terms, "demo": True},
            erp_system="local",
            posted_at=now - timedelta(days=2),
            match={
                "outcome": "matched",
                "issues": [],
                "lines": [],
                "credit": "0",
                "price_variance": "0",
                "ran_at": now.isoformat(),
                "note": "Non-PO service invoice approved by the budget owner (demo data).",
            },
            match_runs=1,
            first_pass_matched=True,
            released_at=now - timedelta(days=2),
            created_by=p.me.id,
        )
        session.add(inv)
        await session.flush()
        inv.erp_ref = inv.reference
    out.loaded.append(
        "5 approved invoices for the payment run (a discount, an overdue one, one over "
        "USD 25,000, a recent bank change)"
    )


async def _clients(session: AsyncSession, p: People, out: DemoResult) -> None:
    if await session.scalar(select(FpClient.id).where(FpClient.name == "Apex Veterinary Group")):
        out.skipped.append("Client accounts")
        return
    now, today = utcnow(), utcnow().date()

    async def code() -> str:
        n = (await session.scalar(select(func.count()).select_from(FpClient)) or 0) + 1
        while await session.scalar(select(FpClient.id).where(FpClient.code == f"C-{n:05d}")):
            n += 1
        return f"C-{n:05d}"

    def month_start(back: int) -> date:
        n = today.year * 12 + today.month - 1 - back
        return date(n // 12, n % 12 + 1, 1)

    specs = [
        (
            "Apex Veterinary Group",
            "apexvet.gia@yopmail.com",
            "40 Grove St, New York NY 10014",
            None,
            Decimal("50"),
            "Due on receipt",
            "high",
        ),
        (
            "Lumen Pharma Services",
            "lumenpharma.gia@yopmail.com",
            "5 Park Ave, New York NY 10016",
            Decimal("60000"),
            Decimal("0"),
            "Net 30",
            "low",
        ),
        (
            "Seaside Food Testing",
            "seasidefood.gia@yopmail.com",
            "2 Dock Rd, Philadelphia PA 19106",
            Decimal("20000"),
            Decimal("0"),
            "Net 30",
            "medium",
        ),
    ]
    made: list[FpClient] = []
    for name, email, address, limit, deposit, terms, risk in specs:
        c = FpClient(
            code=await code(),
            status=ClientStatus.ACTIVE,
            name=name,
            country="US",
            address=address,
            billing_email=email,
            contacts=[{"name": "Accounts payable", "email": email, "phone": "", "role": "AP"}],
            currency="USD",
            credit_limit=limit,
            deposit_pct=deposit,
            payment_terms=terms,
            risk=risk,
            approved_by=p.owner.id,
            last_reviewed_at=now - timedelta(days=210),
            next_review_on=today + timedelta(days=155),
        )
        session.add(c)
        await session.flush()
        await push(session, c)
        made.append(c)
    apex, lumen, seaside = made
    for i in range(8):  # Apex: 8 months, all paid early -> the monitor proposes credit
        issued = month_start(8 - i)
        session.add(
            FpClientHistory(
                client_code=apex.code,
                invoice_number=f"AR-1{i:03d}",
                amount=Decimal(3200 + 450 * (i % 4)),
                issued_on=issued,
                due_on=issued + timedelta(days=7),
                paid_on=issued + timedelta(days=3),
            )
        )
    for i in range(6):  # Lumen: one invoice 75 days overdue -> the monitor proposes a hold
        issued = month_start(6 - i)
        session.add(
            FpClientHistory(
                client_code=lumen.code,
                invoice_number=f"AR-2{i:03d}",
                amount=Decimal(18000 + 1500 * i),
                issued_on=issued,
                due_on=issued + timedelta(days=30),
                paid_on=issued + timedelta(days=34),
            )
        )
    session.add(
        FpClientHistory(
            client_code=lumen.code,
            invoice_number="AR-2099",
            amount=Decimal("21400"),
            issued_on=today - timedelta(days=105),
            due_on=today - timedelta(days=75),
            paid_on=None,
        )
    )
    for i in range(7):  # Seaside: on time, 92% of the limit used -> the monitor proposes a raise
        issued = month_start(9 - i)
        session.add(
            FpClientHistory(
                client_code=seaside.code,
                invoice_number=f"AR-3{i:03d}",
                amount=Decimal(6500 + 300 * i),
                issued_on=issued,
                due_on=issued + timedelta(days=30),
                paid_on=issued + timedelta(days=28),
            )
        )
    for n, (amount, back) in enumerate(((Decimal("9800"), 20), (Decimal("8700"), 6))):
        issued = today - timedelta(days=back)
        session.add(
            FpClientHistory(
                client_code=seaside.code,
                invoice_number=f"AR-39{n}",
                amount=amount,
                issued_on=issued,
                due_on=issued + timedelta(days=30),
                paid_on=None,
            )
        )

    # An application waiting for the credit controller (opened by the other admin)
    app = FpClientApplication(
        status=ApplicationStatus.SUBMITTED,
        client_name="Meridian Health Partners",
        client_email="meridian.gia@yopmail.com",
        invited_by=p.owner.id,
        invited_at=now - timedelta(days=3),
        submitted_at=now - timedelta(hours=26),
        submissions=1,
        legal_name="Meridian Health Partners LLC",
        tax_id="84-2219034",
        country="US",
        address="455 Peachtree St NE, Atlanta GA 30308",
        billing_email="meridian.gia@yopmail.com",
        contacts=[
            {
                "name": "Grace Okafor",
                "email": "meridian.gia@yopmail.com",
                "phone": "+1 404 555 0190",
                "role": "Lab director",
            }
        ],
        currency="USD",
        requested_limit=Decimal("60000"),
        requested_terms="Net 45",
        expected_monthly=Decimal("20000"),
        years_trading=4,
        first_issues=0,
        agent_ran_at=now - timedelta(hours=26),
    )
    session.add(app)
    await session.flush()
    report_on = (today - timedelta(days=25)).isoformat()
    docs = {
        ClientDocumentKind.REGISTRATION: [
            "State of Georgia - Certificate of Organization",
            "Meridian Health Partners LLC",
            "File number GA-2022-0098811",
        ],
        ClientDocumentKind.TAX: [
            "Form W-9",
            "Name: Meridian Health Partners LLC",
            "Employer identification number: 84-2219034",
        ],
        ClientDocumentKind.CREDIT_REPORT: [
            "Dun & Bradstreet Business Information Report",
            "Subject: Meridian Health Partners LLC",
            f"Report date: {report_on}",
            "PAYDEX score: 61 of 100",
            "Recommended credit limit: USD 40,000",
            "Average days beyond terms: 12",
            "Suits, liens and judgments: 1",
            "Years in business: 4",
        ],
        ClientDocumentKind.TRADE_REFERENCE: [
            "Coastal Reagents Inc - Trade reference",
            "Customer: Meridian Health Partners LLC",
            "Payment behaviour: slow",
        ],
    }
    for kind, lines in docs.items():
        data = pdf.render([(ln, 11, i == 0) for i, ln in enumerate(lines)])
        session.add(
            FpClientDocument(
                application_id=app.id,
                kind=kind,
                filename=f"meridian-{kind.value}.pdf",
                content_type="application/pdf",
                size=len(data),
                sha256=hashlib.sha256(data).hexdigest(),
                content=data,
            )
        )

    def read(kind: str, **f: Any) -> dict[str, Any]:
        return {
            **dict.fromkeys(client_agents.ClientDocRead.model_fields),
            "document_type": kind,
            **f,
            "kind": kind,
            "verified": True,
            "filename": f"meridian-{kind}.pdf",
        }

    app.extraction = {
        "notes": [],
        "documents": [
            read("registration", company_name="Meridian Health Partners LLC"),
            read("tax", company_name="Meridian Health Partners LLC", tax_id="84-2219034"),
            read(
                "credit_report",
                bureau="Dun & Bradstreet",
                report_date=report_on,
                credit_score=61,
                score_max=100,
                risk_rating="Moderate risk",
                recommended_limit="USD 40,000",
                days_beyond_terms=12,
                legal_filings=1,
                years_in_business=4,
            ),
            read("trade_reference", referee="Coastal Reagents Inc", payment_behaviour="slow"),
        ],
    }
    app.checks = [
        {
            "key": k,
            "label": label,
            "status": "pass",
            "detail": detail,
            "clearable": False,
            "gap": None,
        }
        for k, label, detail in (
            ("documents", "Business registration and tax document received", "Both received."),
            ("tax_id_format", "Tax ID format (US EIN)", "Valid format."),
            ("tax_id_matches", "Tax ID matches the tax document", "Same as the document."),
            ("name_matches", "Legal name matches the business registration", "Same name."),
            ("credit_report", "Credit report is recent", f"Dun & Bradstreet of {report_on}."),
            ("sanctions", "Sanctions screening (OFAC SDN)", "No match (demo data)."),
        )
    ]
    settings = await current(session)
    app.proposal = client_agents.assess(app, settings.max_new_client_limit)
    app.status, app.proposed_at = ApplicationStatus.PROPOSED, now - timedelta(hours=26)
    out.loaded.append(
        f"3 client accounts with billing history ({apex.code} Apex, {lumen.code} Lumen, "
        f"{seaside.code} Seaside) "
        "and Meridian's application waiting for the credit controller"
    )


async def _billing(session: AsyncSession, p: People, ctx: RequestContext, out: DemoResult) -> None:
    if await session.scalar(select(func.count()).select_from(FpFee)):
        out.skipped.append("Fee schedule and lab submissions")
        return
    clients = {c.name: c for c in await session.scalars(select(FpClient))}
    if not {"Apex Veterinary Group", "Lumen Pharma Services", "Seaside Food Testing"} <= set(
        clients
    ):
        out.notes.append("Billing demo skipped: the demo client accounts aren't there.")
        return
    apex, lumen, seaside = (
        clients[n]
        for n in ("Apex Veterinary Group", "Lumen Pharma Services", "Seaside Food Testing")
    )
    data, _ = fee_workbook.template()
    parsed = fee_workbook.parse(data)
    for c in parsed.contracts:  # the template's contract is for the demo Lumen account
        c.client_code = lumen.code
    session.add_all([*parsed.fees, *parsed.contracts, *parsed.taxes])
    await session.flush()

    def sub(client: FpClient, lines: list[dict[str, Any]], **extra: Any) -> SubmissionIn:
        return SubmissionIn.model_validate({"client_code": client.code, "lines": lines, **extra})

    await billing.create_submission(
        session,
        sub(
            apex,
            [
                {
                    "item_ref": "D-101",
                    "stone_type": "diamond",
                    "carat": "0.90",
                    "service_code": "GRD",
                },
                {
                    "item_ref": "D-102",
                    "stone_type": "diamond",
                    "carat": "1.20",
                    "service_code": "GRD",
                },
            ],
            estimate="260",
            notes="Two loose diamonds for grading",
        ),
        ctx,
        actor_id=p.me.id,
        via="screen",
    )
    await billing.create_submission(
        session,
        sub(
            lumen,
            [
                {"item_ref": "C-201", "stone_type": "coloured", "service_code": "CID"},
                {
                    "item_ref": "D-202",
                    "stone_type": "diamond",
                    "carat": "2.10",
                    "service_code": "GRD",
                    "special_price": "150",
                    "special_reason": "Volume deal agreed by client services",
                },
            ],
            turnaround="express",
            estimate="320",
            notes="Sapphire ID and a 2.1 ct diamond, express",
        ),
        ctx,
        actor_id=p.me.id,
        via="screen",
    )
    flagged = await billing.create_submission(
        session,
        sub(
            seaside,
            [
                {"item_ref": "P-301", "stone_type": "pearl", "service_code": "PRL", "quantity": 3},
                {"item_ref": "S-302", "stone_type": "other", "service_code": "XRF"},
            ],
            estimate="280",
            notes="Pearl strand and a screening request",
        ),
        ctx,
        actor_id=p.me.id,
        via="import",
    )
    # Flagged on purpose (XRF isn't in the demo fee schedule): it waits for the analyst, so
    # nothing is emailed
    inv = await billing.report_issued(
        session,
        flagged,
        [
            PerformedIn(item_ref="P-301", service_code="PRL", quantity=3),
            PerformedIn(item_ref="S-302", service_code="XRF"),
            PerformedIn(item_ref="P-301", service_code="LSR"),
        ],
        ctx,
        actor_id=None,
        via="api",
    )
    assert inv.status == SalesInvoiceStatus.REVIEW  # noqa: S101
    out.loaded.append(
        "Fee schedule (with a Lumen contract price and NY/PA tax), 2 submissions in the lab "
        f"(Apex: clean; Lumen: flagged) and {inv.reference} waiting for the billing analyst"
    )


async def _sanctions(session: AsyncSession, out: DemoResult) -> None:
    if (await sanctions.info(session)).entries:
        out.skipped.append("Sanctions list")
        return
    try:
        count = await sanctions.load(session)
    except Exception as exc:  # the download may be blocked: screening then fails until loaded
        out.notes.append(
            f"The OFAC sanctions list couldn't be downloaded ({exc}); load it on the Vendors page."
        )
        return
    out.loaded.append(f"OFAC sanctions list ({count:,} entries)")


class DemoNeedsSecondAdminError(AppError):
    status_code = 409
    code = "demo_needs_second_admin"
    message = (
        "The demo needs a second Finance Admin to approve what you request. Add one in Admin "
        "Settings > Users (or turn on self-approval in Setup), then load the demo data again. "
        "Nothing was loaded."
    )


async def load(session: AsyncSession, me: User, ctx: RequestContext) -> DemoResult:
    out = DemoResult()
    p = await _people(session, me)
    if p.alone and not (await current(session)).allow_self_approval:
        raise DemoNeedsSecondAdminError
    await _reference(session, p, ctx, out)  # commits (the reference import)
    await _bank_accounts(session, p, out)
    await _purchasing(session, p, out)
    await _ready_invoices(session, p, out)
    await _clients(session, p, out)
    await session.flush()
    await _billing(session, p, ctx, out)
    await session.commit()
    await _sanctions(session, out)
    await session.commit()
    if p.alone:
        out.notes.append(
            "You're the only Finance Admin, so with self-approval on you are every approver "
            "too. Add a second Finance Admin (Admin Settings > Users) for real two-person steps."
        )
    else:
        out.notes.append(
            f"Approvals that need a second person go to {p.owner.full_name} ({p.owner.email})."
        )
    record_event(
        session,
        "fpod.demo_data_loaded",
        ctx,
        actor_id=me.id,
        loaded=out.loaded,
        summary="Loaded Finance POD demo data: "
        + ("; ".join(out.loaded) if out.loaded else "already there"),
    )
    await session.commit()
    return out
