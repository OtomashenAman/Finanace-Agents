"""Bank statements in any format become bank receipts (money in) for Bank-to-Invoice."""

import io
from datetime import date
from decimal import Decimal

import pytest
from openpyxl import Workbook

from src.app.finance_pod import pdf
from src.app.service_pod.core.snapshots.exceptions import SnapshotInvalidError
from src.app.service_pod.core.snapshots.importers import bank_statement
from tests.conftest import FakeLLM


async def read(data: bytes, name: str, llm: FakeLLM | None = None) -> bank_statement.Statement:
    return await bank_statement.read(data, name, "USD", llm or FakeLLM())  # type: ignore[arg-type]


async def test_a_bank_csv_in_its_own_layout() -> None:
    """A preamble, day-first dates, separate credit/debit columns, thousands separators."""
    csv = (
        "First Harbor Bank - Account statement\n"
        "Account,****4410\n"
        "\n"
        "Posting Date,Transaction Details,Debit,Credit,Balance,Bank Reference\n"
        '05/11/2026,"WIRE FROM HARBOR DISTRIBUTION INV 101",,"9,000.00","19,000.00",FT26309ABC\n'
        "06/11/2026,CARD PAYMENT OFFICE SUPPLIES,45.10,,18954.90,\n"
        '17/11/2026,"ACH CREDIT NORTHWIND LABS",,1250.00,20204.90,\n'
        "Closing balance,,,,20204.90,\n"
    )
    s = await read(csv.encode(), "statement.csv")
    assert s.method == "CSV" and s.money_out == 1
    first, second = s.receipts
    assert (first.reference, first.payer, first.date, first.amount) == (
        "FT26309ABC",
        "HARBOR DISTRIBUTION INV 101",
        date(2026, 11, 5),
        Decimal("9000.00"),
    )
    assert second.date == date(2026, 11, 17) and second.reference.startswith("BNK-261117-")
    again = await read(csv.encode(), "statement.csv")  # the same file: the same references
    assert [r.reference for r in again.receipts] == [r.reference for r in s.receipts]


async def test_the_old_template_still_works() -> None:
    csv = "reference,payer,date,amount,currency,cleared\nWIRE-1,Harbor,2026-11-05,9000,USD,no\n"
    [r] = (await read(csv.encode(), "x.csv")).receipts
    assert (r.reference, r.payer, r.cleared) == ("WIRE-1", "Harbor", False)


async def test_excel_with_a_signed_amount_and_european_numbers() -> None:
    book = Workbook()
    ws = book.active
    assert ws is not None
    ws.append(["Statement", None, None])
    ws.append(["Date", "Description", "Amount", "Currency"])
    ws.append([date(2026, 11, 3), "SEPA TRANSFER FROM MERIDIAN GMBH", "1.234,56", "EUR"])
    ws.append([date(2026, 11, 4), "Bank fee", "-12,00", "EUR"])
    buffer = io.BytesIO()
    book.save(buffer)
    s = await read(buffer.getvalue(), "statement.xlsx")
    [r] = s.receipts
    assert (s.method, r.amount, r.currency, r.payer) == (
        "Excel",
        Decimal("1234.56"),
        "EUR",
        "MERIDIAN GMBH",
    )


async def test_ofx_qfx() -> None:
    ofx = """OFXHEADER:100
DATA:OFXSGML
<OFX><BANKMSGSRSV1><STMTTRNRS><STMTRS><CURDEF>USD<BANKTRANLIST>
<STMTTRN><TRNTYPE>CREDIT<DTPOSTED>20261105120000[-5:EST]
<TRNAMT>9000.00<FITID>OFX-77<NAME>HARBOR DISTRIBUTION<MEMO>INV 101
<STMTTRN><TRNTYPE>DEBIT<DTPOSTED>20261106
<TRNAMT>-45.10<FITID>OFX-78<NAME>OFFICE DEPOT
</BANKTRANLIST></STMTRS></STMTTRNRS></BANKMSGSRSV1></OFX>"""
    s = await read(ofx.encode(), "download.qfx")
    [r] = s.receipts
    assert (s.method, r.reference, r.payer, r.amount, s.money_out) == (
        "OFX/QFX",
        "OFX-77",
        "HARBOR DISTRIBUTION",
        Decimal("9000.00"),
        1,
    )


async def test_camt_053() -> None:
    xml = """<?xml version="1.0"?>
<Document xmlns="urn:iso:std:iso:20022:tech:xsd:camt.053.001.08"><BkToCstmrStmt><Stmt>
<Ntry><Amt Ccy="USD">9000.00</Amt><CdtDbtInd>CRDT</CdtDbtInd><Sts><Cd>BOOK</Cd></Sts>
<BookgDt><Dt>2026-11-05</Dt></BookgDt><AcctSvcrRef>CAMT-1</AcctSvcrRef>
<NtryDtls><TxDtls><Refs><EndToEndId>E2E-101</EndToEndId></Refs>
<RltdPties><Dbtr><Nm>Harbor Distribution</Nm></Dbtr></RltdPties>
<RmtInf><Ustrd>INV 101</Ustrd></RmtInf>
</TxDtls></NtryDtls></Ntry>
<Ntry><Amt Ccy="USD">20.00</Amt><CdtDbtInd>DBIT</CdtDbtInd>
<BookgDt><Dt>2026-11-06</Dt></BookgDt></Ntry>
<Ntry><Amt Ccy="USD">500.00</Amt><CdtDbtInd>CRDT</CdtDbtInd><Sts><Cd>PDNG</Cd></Sts>
<BookgDt><Dt>2026-11-07</Dt></BookgDt><AcctSvcrRef>CAMT-3</AcctSvcrRef></Ntry>
</Stmt></BkToCstmrStmt></Document>"""
    s = await read(xml.encode(), "camt053.xml")
    first, pending = s.receipts
    assert (first.reference, first.payer, first.cleared) == ("E2E-101", "Harbor Distribution", True)
    assert (pending.reference, pending.cleared, s.money_out) == ("CAMT-3", False, 1)


async def test_xml_with_entities_is_refused() -> None:
    evil = (
        b'<?xml version="1.0"?><!DOCTYPE x [<!ENTITY a "aaaa">]><Document>camt.053 &a;</Document>'
    )
    with pytest.raises(SnapshotInvalidError, match="DOCTYPE"):
        await read(evil, "x.xml")


async def test_mt940() -> None:
    mt = (
        ":20:STMT2611\n:25:021000021/4410\n:28C:00309/1\n:60F:C261104USD10000,00\n"
        ":61:2611051105C9000,00NTRFHARB101//BNK7781\n:86:HARBOR DISTRIBUTION INV 101\n"
        ":61:2611061106D45,10NMSCNONREF//BNK7782\n:86:CARD OFFICE SUPPLIES\n"
        ":62F:C261106USD18954,90\n"
    )
    s = await read(mt.encode(), "statement.sta")
    [r] = s.receipts
    assert (s.method, r.reference, r.amount, r.date, r.proof_reference) == (
        "MT940",
        "BNK7781",
        Decimal("9000.00"),
        date(2026, 11, 5),
        "HARBOR DISTRIBUTION INV 101",
    )


async def test_a_pdf_statement_is_read_by_the_ai_and_checked_against_its_text() -> None:
    document = pdf.render(
        [
            ("Harbor Bank statement, November 2026", 12, True),
            ("2026-11-05  Wire from Harbor Distribution  ref FT9001   9,000.00 CR", 10, False),
            ("2026-11-06  Office Depot card payment        45.10 DR", 10, False),
        ]
    )
    llm = FakeLLM()
    llm.output = {
        "currency": "USD",
        "transactions": [
            {
                "date": "2026-11-05",
                "description": "Wire from Harbor Distribution",
                "payer": "Harbor Distribution",
                "reference": "FT9001",
                "amount": "9,000.00",
                "direction": "in",
            },
            {
                "date": "2026-11-06",
                "description": "Office Depot",
                "payer": None,
                "reference": None,
                "amount": "45.10",
                "direction": "out",
            },
        ],
    }
    s = await read(document, "statement.pdf", llm)
    [r] = s.receipts
    assert (s.method, r.reference, r.amount, s.money_out) == (
        "AI reading of the document",
        "FT9001",
        Decimal("9000.00"),
        1,
    )
    llm.output["transactions"][0]["amount"] = "9,500.00"  # not in the document: refused
    with pytest.raises(SnapshotInvalidError, match="couldn't be read reliably"):
        await read(document, "statement.pdf", llm)


async def test_a_statement_with_only_money_out_says_so() -> None:
    csv = "Date,Description,Amount\n2026-11-05,Rent,-2000\n2026-11-06,Fees,-10\n"
    with pytest.raises(SnapshotInvalidError, match="no money in"):
        await read(csv.encode(), "x.csv")
