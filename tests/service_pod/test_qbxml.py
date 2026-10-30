from typing import Any

from src.app.entities.models import LegalEntity

QBXML = """<?xml version="1.0"?>
<QBXML><QBXMLMsgsRs>
  <CompanyQueryRs statusCode="0">
    <CompanyRet><CompanyName>E-Solutions Inc</CompanyName></CompanyRet>
  </CompanyQueryRs>
  <CustomerQueryRs statusCode="0" iteratorRemainingCount="{remaining}">
    <CustomerRet><ListID>80000001</ListID><Name>Harbor Distribution</Name>
      <FullName>Harbor Distribution</FullName><Email>ap@harbor.example</Email></CustomerRet>
  </CustomerQueryRs>
  <InvoiceQueryRs statusCode="0">
    <InvoiceRet><TxnID>1A-1</TxnID><CustomerRef><ListID>80000001</ListID></CustomerRef>
      <TxnDate>2026-09-01</TxnDate><RefNumber>INV-101</RefNumber><DueDate>2026-10-01</DueDate>
      <Subtotal>15000.00</Subtotal><BalanceRemaining>9000.00</BalanceRemaining></InvoiceRet>
  </InvoiceQueryRs>
  <ReceivePaymentQueryRs statusCode="0">
    <ReceivePaymentRet><TxnID>2B-7</TxnID><CustomerRef><ListID>80000001</ListID></CustomerRef>
      <TxnDate>2026-11-05</TxnDate><RefNumber>WIRE-2901</RefNumber><TotalAmount>6000.00</TotalAmount>
      <AppliedToTxnRet><TxnID>1A-1</TxnID><PaymentAmount>6000.00</PaymentAmount></AppliedToTxnRet>
    </ReceivePaymentRet>
  </ReceivePaymentQueryRs>
  <AccountQueryRs statusCode="0">
    <AccountRet><ListID>A1</ListID><FullName>Consulting Revenue</FullName>
      <AccountType>Income</AccountType></AccountRet>
    <AccountRet><ListID>A2</ListID><FullName>Old</FullName><AccountType>NonPosting</AccountType></AccountRet>
  </AccountQueryRs>
</QBXMLMsgsRs></QBXML>"""


async def _post(client: Any, entity: LegalEntity, xml: str) -> Any:
    return await client.post(
        "/api/v1/pod/snapshots/qbxml",
        files={"file": ("export.xml", xml.encode(), "application/xml")},
        data={
            "entity_id": str(entity.id),
            "currency": "USD",
            "basis": "Accrual",
            "as_of": "2026-11-05",
        },
    )


async def test_qbxml_import(ar_team: dict[str, Any], entity: LegalEntity) -> None:
    r = await _post(ar_team["poster"], entity, QBXML.format(remaining=0))
    assert r.status_code == 201, r.text
    snap = r.json()["snapshot"]
    assert snap["source_type"] == "qbxml"
    assert snap["company_name"] == "E-Solutions Inc"
    assert snap["coverage"] == ["customers", "invoices", "payments", "accounts"]
    rows = await ar_team["poster"].get(
        f"/api/v1/pod/snapshots/{snap['id']}/rows?collection=payments"
    )
    (payment,) = rows.json()["rows"]
    assert payment["reference"] == "WIRE-2901"
    assert payment["allocations"] == [{"invoice_id": "1A-1", "amount": "6000"}]
    accounts = await ar_team["poster"].get(
        f"/api/v1/pod/snapshots/{snap['id']}/rows?collection=accounts"
    )
    assert [a["name"] for a in accounts.json()["rows"]] == ["Consulting Revenue"]


async def test_incomplete_or_unsafe_exports_are_refused(
    ar_team: dict[str, Any], entity: LegalEntity
) -> None:
    r = await _post(ar_team["poster"], entity, QBXML.format(remaining=12))
    assert r.status_code == 422
    assert "incomplete" in r.json()["detail"]["message"]

    evil = '<?xml version="1.0"?><!DOCTYPE x [<!ENTITY a "aaaa">]><QBXML/>'
    r = await _post(ar_team["poster"], entity, evil)
    assert r.status_code == 422

    failed = QBXML.format(remaining=0).replace(
        '<InvoiceQueryRs statusCode="0">', '<InvoiceQueryRs statusCode="3100" statusMessage="bad">'
    )
    r = await _post(ar_team["poster"], entity, failed)
    assert "Invoice query failed" in r.json()["detail"]["message"]
