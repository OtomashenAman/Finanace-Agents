import type { RecordType, SourceStatus } from "./api"

export const STATUS: Record<SourceStatus, { label: string; tone: string }> = {
  connected: { label: "Connected", tone: "bg-emerald-50 text-emerald-700" },
  ready: { label: "Imported", tone: "bg-emerald-50 text-emerald-700" },
  pending_auth: { label: "Authorization pending", tone: "bg-muted text-muted-foreground" },
  needs_reauth: { label: "Needs re-authorization", tone: "bg-amber-50 text-amber-800" },
  error: { label: "Sync failed", tone: "bg-destructive/10 text-destructive" },
}

export const RECORD_LABELS: Record<RecordType, string> = {
  vendor: "Vendors",
  bill: "Bills",
  purchase_order: "Purchase orders",
  account: "Accounts",
  customer: "Customers",
  invoice: "Customer invoices",
  payment: "Customer payments",
  expense: "Expenses",
}

/** Singular, for pickers: "Pick a bill" */
export const RECORD_NOUN: Record<string, string> = {
  vendor: "vendor",
  bill: "bill",
  purchase_order: "purchase order",
  account: "account",
  customer: "customer",
  invoice: "invoice",
  payment: "payment",
  expense: "expense",
  // what a prefill pulled in alongside the picked record (run source snapshots)
  oldest_open_invoice: "oldest open invoice",
}

export const FIELD_LABELS: Record<string, string> = {
  external_id: "ID (optional, unique per row)",
  name: "Name",
  email: "Email",
  tax_id: "Tax ID",
  active: "Active (yes/no)",
  doc_number: "Invoice / bill number",
  vendor_name: "Vendor / merchant",
  total: "Total amount",
  tax_total: "Tax amount",
  bill_date: "Bill date",
  due_date: "Due date",
  po_number: "PO number",
  account: "GL account / category",
  received_amount: "Received amount",
  status: "Status",
  po_date: "PO date",
  number: "Account number",
  account_type: "Account type",
  customer_name: "Customer",
  balance: "Open balance",
  invoice_date: "Invoice date",
  paid_date: "Paid date",
  reference_number: "Payment reference",
  payment_date: "Payment date",
  invoice_number: "Applied to invoice",
  applied_amount: "Amount applied",
  unapplied_amount: "Unapplied amount",
  memo: "Memo / remittance",
  transaction_id: "Transaction ID",
  expense_date: "Date",
  payment_type: "Payment type",
  employee: "Employee",
  has_receipt: "Receipt attached (yes/no)",
}

export function fieldLabel(name: string): string {
  return FIELD_LABELS[name] ?? name
}
