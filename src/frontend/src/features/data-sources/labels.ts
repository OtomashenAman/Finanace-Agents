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
}

/** Singular, for pickers: "Pick a bill" */
export const RECORD_NOUN: Record<string, string> = {
  vendor: "vendor",
  bill: "bill",
  purchase_order: "purchase order",
  account: "account",
}

export const FIELD_LABELS: Record<string, string> = {
  external_id: "ID (optional, unique per row)",
  name: "Name",
  email: "Email",
  tax_id: "Tax ID",
  active: "Active (yes/no)",
  doc_number: "Invoice / bill number",
  vendor_name: "Vendor",
  total: "Total amount",
  tax_total: "Tax amount",
  bill_date: "Bill date",
  due_date: "Due date",
  po_number: "PO number",
  account: "GL account",
  received_amount: "Received amount",
  status: "Status",
  po_date: "PO date",
  number: "Account number",
  account_type: "Account type",
}

export function fieldLabel(name: string): string {
  return FIELD_LABELS[name] ?? name
}
