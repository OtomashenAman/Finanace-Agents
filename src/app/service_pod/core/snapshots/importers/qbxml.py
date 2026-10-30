"""QuickBooks Desktop / Enterprise qbXML query responses -> a SnapshotDocument.

Reads Company, Customer, Invoice, ReceivePayment and Account query responses from one file.
Every response must have completed (status OK, no iterator rows left); a collection whose
response is absent stays absent. P&L, GL, balance sheets and close status aren't in these
responses and are never synthesized from them.
"""

import xml.etree.ElementTree as ET
from datetime import date
from decimal import Decimal, InvalidOperation

from pydantic import ValidationError

from src.app.service_pod.core.snapshots.contract import (
    Account,
    AccountClass,
    Allocation,
    Basis,
    Customer,
    Invoice,
    Payment,
    Provenance,
    SnapshotDocument,
)
from src.app.service_pod.core.snapshots.exceptions import SnapshotInvalidError

# qbXML statusCode: 0 = OK, 1 = the query matched nothing (an empty, complete answer)
_OK = {"0", "1"}
_CLASSES = {
    "Income": AccountClass.INCOME,
    "OtherIncome": AccountClass.OTHER_INCOME,
    "CostOfGoodsSold": AccountClass.COST_OF_GOODS_SOLD,
    "Expense": AccountClass.EXPENSE,
    "OtherExpense": AccountClass.OTHER_EXPENSE,
    "Bank": AccountClass.ASSET,
    "AccountsReceivable": AccountClass.ASSET,
    "OtherCurrentAsset": AccountClass.ASSET,
    "FixedAsset": AccountClass.ASSET,
    "OtherAsset": AccountClass.ASSET,
    "AccountsPayable": AccountClass.LIABILITY,
    "CreditCard": AccountClass.LIABILITY,
    "OtherCurrentLiability": AccountClass.LIABILITY,
    "LongTermLiability": AccountClass.LIABILITY,
    "Equity": AccountClass.EQUITY,
}


def _text(node: ET.Element, path: str) -> str | None:
    found = node.find(path)
    return found.text.strip() if found is not None and found.text else None


def _need(node: ET.Element, path: str, what: str) -> str:
    value = _text(node, path)
    if value is None:
        raise SnapshotInvalidError(f"{what}: {path} is missing.")
    return value


def _money(node: ET.Element, path: str, what: str, default: str | None = None) -> Decimal:
    raw = _text(node, path) or default
    if raw is None:
        raise SnapshotInvalidError(f"{what}: {path} is missing.")
    try:
        return Decimal(raw)
    except InvalidOperation as exc:
        raise SnapshotInvalidError(f"{what}: {path} isn't a number.") from exc


def _date(node: ET.Element, path: str, what: str) -> date:
    try:
        return date.fromisoformat(_need(node, path, what))
    except ValueError as exc:
        raise SnapshotInvalidError(f"{what}: {path} isn't a date.") from exc


def _responses(root: ET.Element) -> dict[str, ET.Element]:
    msgs = root.find("QBXMLMsgsRs")
    if msgs is None:
        raise SnapshotInvalidError("No QBXMLMsgsRs element: this isn't a qbXML response file.")
    found: dict[str, ET.Element] = {}
    for rs in msgs:
        name = rs.tag.removesuffix("QueryRs")
        if rs.get("statusCode") not in _OK:
            raise SnapshotInvalidError(
                f"The {name} query failed in QuickBooks ({rs.get('statusMessage', 'no message')})."
            )
        if rs.get("iteratorRemainingCount", "0") != "0":
            raise SnapshotInvalidError(f"The {name} export is incomplete (more rows remain).")
        if name in found:
            raise SnapshotInvalidError(f"The {name} response appears twice.")
        found[name] = rs
    return found


def parse_qbxml(
    data: bytes,
    *,
    entity_code: str,
    currency: str,
    basis: Basis,
    as_of: date,
    provenance: Provenance,
    filename: str,
) -> SnapshotDocument:
    if b"<!DOCTYPE" in data or b"<!ENTITY" in data:
        raise SnapshotInvalidError("qbXML files with DTDs or entities aren't accepted.")
    try:
        root = ET.fromstring(data)  # noqa: S314 - see above
    except ET.ParseError as exc:
        raise SnapshotInvalidError(f"Not valid XML: {exc}") from exc
    rs = _responses(root)
    company = rs.get("Company")
    if company is None or company.find("CompanyRet") is None:
        raise SnapshotInvalidError("The file needs the Company query response.")
    company_name = _need(company, "CompanyRet/CompanyName", "Company")

    customers = None
    if "Customer" in rs:
        customers = [
            Customer(
                id=_need(c, "ListID", "Customer"),
                name=_text(c, "FullName") or _need(c, "Name", "Customer"),
                email=_text(c, "Email"),
                contact_name=_text(c, "Contact"),
            )
            for c in rs["Customer"].findall("CustomerRet")
        ]
    invoices = None
    if "Invoice" in rs:
        invoices = []
        for inv in rs["Invoice"].findall("InvoiceRet"):
            what = f"Invoice {_text(inv, 'RefNumber') or _text(inv, 'TxnID')}"
            subtotal = _money(inv, "Subtotal", what)
            tax = _money(inv, "SalesTaxTotal", what, default="0")
            invoices.append(
                Invoice(
                    id=_need(inv, "TxnID", what),
                    number=_text(inv, "RefNumber") or _need(inv, "TxnID", what),
                    customer_id=_need(inv, "CustomerRef/ListID", what),
                    txn_date=_date(inv, "TxnDate", what),
                    due_date=_date(inv, "DueDate", what),
                    original_amount=subtotal + tax,
                    balance=_money(inv, "BalanceRemaining", what),
                    terms=_text(inv, "TermsRef/FullName"),
                )
            )
    payments = None
    if "ReceivePayment" in rs:
        payments = []
        for pay in rs["ReceivePayment"].findall("ReceivePaymentRet"):
            what = f"Payment {_text(pay, 'RefNumber') or _text(pay, 'TxnID')}"
            payments.append(
                Payment(
                    id=_need(pay, "TxnID", what),
                    customer_id=_need(pay, "CustomerRef/ListID", what),
                    date=_date(pay, "TxnDate", what),
                    amount=_money(pay, "TotalAmount", what),
                    currency=currency,
                    reference=_text(pay, "RefNumber") or _need(pay, "TxnID", what),
                    allocations=[
                        Allocation(
                            invoice_id=_need(a, "TxnID", what),
                            amount=_money(a, "PaymentAmount", what),
                        )
                        for a in pay.findall("AppliedToTxnRet")
                    ],
                )
            )
    accounts = None
    if "Account" in rs:
        accounts = [
            Account(
                id=_need(a, "ListID", "Account"),
                name=_text(a, "FullName") or _need(a, "Name", "Account"),
                number=_text(a, "AccountNumber"),
                classification=_CLASSES[_need(a, "AccountType", "Account")],
            )
            for a in rs["Account"].findall("AccountRet")
            if _text(a, "AccountType") in _CLASSES
        ]
    try:
        return SnapshotDocument(
            provenance=provenance,
            company_id=company_name,
            company_name=company_name,
            entity=entity_code,
            currency=currency,
            basis=basis,
            as_of=as_of,
            source_reference=f"qbXML export {filename}",
            customers=customers,
            invoices=invoices,
            payments=payments,
            accounts=accounts,
        )
    except ValidationError as exc:
        first = exc.errors()[0]
        raise SnapshotInvalidError(
            f"{'.'.join(str(p) for p in first['loc'])}: {first['msg']}"
        ) from exc
