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
  account_balance: "Month-end account balances",
  subledger_total: "Month-end AR/AP totals",
  period_result: "Monthly P&L (actual and budget)",
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
  account_balance: "account balance",
  subledger_total: "subledger total",
  period_result: "P&L month",
  // what a prefill pulled in alongside the picked record (run source snapshots)
  oldest_open_invoice: "oldest open invoice",
  // a prefill from parameters (e.g. Treasury's cash position)
  parameters: "parameters",
  summary: "summary",
  bank_accounts: "bank accounts",
  invoices_due: "invoices due (inflows)",
  overdue_invoices: "overdue invoices (not counted)",
  bills_due: "bills due (outflows)",
  // Board Reporting and FP&A: the months behind each total
  months: "months",
  prior_year_months: "same months last year",
  actual_months: "actual by month",
  budget_months: "budget by month",
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
  line_items: "Line items (one per line)",
  service_start: "Service start date",
  service_end: "Service end date",
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
  account_name: "Account",
  account_number: "Account number",
  period: "Period (YYYY-MM)",
  ledger: "Ledger (AR or AP)",
  business_unit: "Business unit (empty: whole company)",
  basis: "Actual or budget",
  revenue: "Revenue",
  cogs: "Cost of goods sold",
  operating_expenses: "Operating expenses",
  operating_profit: "Operating profit (optional: calculated)",
}

export function fieldLabel(name: string): string {
  return FIELD_LABELS[name] ?? name
}
