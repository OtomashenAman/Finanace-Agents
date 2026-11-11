import { apiDownload, apiRequest } from "@/lib/api"

export type InvoiceStatus = "captured" | "duplicate" | "posted" | "exception" | "ready" | "paid" | "rejected"
export type SampleScenario = "match" | "price" | "quantity" | "duplicate"
export type ExceptionStatus ="open" | "waiting_vendor" | "waiting_receipt" | "resolved"
export type ExceptionDecision = "accept" | "credit" | "amend_po" | "reject"

export interface InvoiceLineIn {
  description: string
  quantity: string
  unit_price: string
  po_line: number | null
}

export interface InvoiceIn {
  vendor_code: string | null
  vendor_invoice_number: string | null
  invoice_date: string | null
  due_date: string | null
  currency: string
  tax_code: string | null
  tax_total: string
  total: string | null
  po_reference: string | null
  lines: InvoiceLineIn[]
}

export interface MatchIssue {
  kind: "price" | "quantity" | "no_receipt" | "not_on_po" | "no_po" | "vendor" | "header"
  line: number | null
  message: string
  amount: string | null
}

export interface MatchLine {
  line: number
  description: string
  quantity: string
  unit_price: string
  po_line: number | null
  po_unit_price?: string
  po_quantity?: string
  received?: string
  invoiced_elsewhere?: string
  price_tolerance?: string
  status: "match" | "price_variance" | "quantity_variance" | "no_receipt" | "not_on_po"
}

export interface TrailLine {
  line: number
  po_line: number
  description: string
  ordered: string
  received: string
  billed_before: string
  this_invoice: string
  left_to_bill: string
  po_unit_price: string | null
  unit_price: string
}

export interface MatchExplanation {
  highlights: { text: string; fact_ids: string[] }[]
  facts: { id: string; label: string; value: string }[]
  provenance: Record<string, string | null>
  generated_at: string
}

export interface MatchResult {
  outcome: "matched" | "variance"
  issues: MatchIssue[]
  lines: MatchLine[]
  trail?: TrailLine[]
  price_variance?: string
  credit: string
  tolerances?: { price_pct: string; price_amount: string; qty_pct: string }
  ran_at: string
  note?: string // e.g. an invoice approved without a PO
  explanation?: MatchExplanation
  explanation_error?: string
}

export interface InvoiceException {
  id: string
  invoice_id: string
  invoice_reference: string
  vendor_name: string | null
  po_reference: string | null
  status: ExceptionStatus
  kinds: string[]
  issues: MatchIssue[]
  vendor_query_subject: string | null
  vendor_query_body: string | null
  decision: ExceptionDecision | null
  decided_by_name: string | null
  decided_at: string | null
  note: string | null
  credit_expected: string | null
  credit_received: string | null
  credit_note_ref: string | null
  created_at: string
  resolved_at: string | null
  age_days: number
  total: string | null
  currency: string
}

export interface ReceiptRequest {
  id: string
  po_id: string
  receiver_email: string
  receiver_name: string | null
  status: "open" | "confirmed" | "cancelled"
  nudges: number
  last_nudged_at: string | null
  confirmed_at: string | null
  expires_at: string | null
  link: string | null
}

export interface InvoiceSummary {
  id: string
  reference: string
  status: InvoiceStatus
  paid_at?: string | null
  payment_ref?: string | null
  vendor_code: string | null
  vendor_name: string | null
  vendor_invoice_number: string | null
  invoice_date: string | null
  total: string | null
  currency: string
  po_reference: string | null
  first_pass_matched: boolean | null
  created_at: string
}

export interface DuplicateHit {
  invoice_id: string
  reference: string
  vendor_invoice_number: string | null
  total: string | null
  invoice_date: string | null
  status: string
  reason: string
  strength: "exact" | "likely" | "possible"
}

export interface Invoice extends InvoiceSummary {
  version: number
  due_date: string | null
  tax_code: string | null
  tax_total: string
  po_id: string | null
  filename: string | null
  extraction: (Record<string, unknown> & { error?: string; verified?: boolean }) | null
  validated_by_name: string | null
  validated_at: string | null
  duplicate: {
    hits?: DuplicateHit[]
    explanation?: string
    overridden_by?: string
    override_note?: string
  } | null
  erp_system: string | null
  erp_ref: string | null
  posted_at: string | null
  match: MatchResult | null
  match_runs: number
  released_at: string | null
  rejected_reason: string | null
  lines: (InvoiceLineIn & { position: number; amount: string })[]
  lines_total: string
  exception: InvoiceException | null
  receipt_requests: ReceiptRequest[]
  can_edit: boolean
}

export interface Receipt {
  id: string
  received_on: string
  receiver_email: string | null
  via: string
  notes: string | null
  lines: { po_line: number; quantity: string }[]
  created_at: string
}

export interface ReceiptPortalView {
  status: "open" | "used" | "expired"
  organisation: string
  po_reference: string
  vendor_name: string
  receiver_name: string | null
  invoice_reference: string | null
  lines: { position: number; description: string; ordered: string; unit: string | null; received: string }[]
}

export interface InvoiceMeasures {
  invoices: number
  first_pass_judged: number
  first_pass_matched: number
  first_pass_rate: number | null
  exceptions_open: number
  exception_ageing: Record<string, number>
  exceptions_by_kind: Record<string, number>
  oldest_open_days: number | null
  duplicates_stopped: number
  duplicates_amount: string
  ready_for_coding: number
}

export interface DecisionIn {
  decision: ExceptionDecision
  note: string
  amendments?: { po_line: number; unit_price: string; quantity: string }[]
  credit_expected?: string | null
  query_subject?: string | null
  query_body?: string | null
}

const FP = "/finance-pod"

export const invoicesApi = {
  list: (status?: InvoiceStatus | null, poId?: string | null) => {
    const q = new URLSearchParams()
    if (status) q.set("status", status)
    if (poId) q.set("po_id", poId)
    const s = q.toString()
    return apiRequest<InvoiceSummary[]>(s ? `${FP}/invoices?${s}` : `${FP}/invoices`)
  },
  get: (id: string) => apiRequest<Invoice>(`${FP}/invoices/${id}`),
  capture: (file: File) => {
    const form = new FormData()
    form.append("file", file)
    return apiRequest<Invoice>(`${FP}/invoices/capture`, { method: "POST", form })
  },
  sample: (po_id: string, scenario: SampleScenario) =>
    apiRequest<{ invoice_id: string; reference: string; note: string }>(`${FP}/invoices/sample`, {
      method: "POST",
      json: { po_id, scenario },
    }),
  create: (body: InvoiceIn) => apiRequest<Invoice>(`${FP}/invoices`, { method: "POST", json: body }),
  update: (id: string, version: number, body: InvoiceIn) =>
    apiRequest<Invoice>(`${FP}/invoices/${id}`, { method: "PUT", json: { ...body, expected_version: version } }),
  post: (id: string, version: number) =>
    apiRequest<Invoice>(`${FP}/invoices/${id}/post`, { method: "POST", json: { expected_version: version } }),
  notDuplicate: (id: string, version: number, note: string) =>
    apiRequest<Invoice>(`${FP}/invoices/${id}/not-duplicate`, {
      method: "POST",
      json: { expected_version: version, note },
    }),
  remove: (ids: string[]) =>
    apiRequest<{ deleted: number }>(`${FP}/invoices/delete`, { method: "POST", json: { ids } }),
  explain: (id: string) => apiRequest<Invoice>(`${FP}/invoices/${id}/explain`, { method: "POST" }),
  rematch: (id: string) => apiRequest<Invoice>(`${FP}/invoices/${id}/rematch`, { method: "POST" }),
  reject: (id: string, version: number, note: string) =>
    apiRequest<Invoice>(`${FP}/invoices/${id}/reject`, { method: "POST", json: { expected_version: version, note } }),
  downloadFile: (inv: { id: string; filename: string | null }) =>
    apiDownload(`${FP}/invoices/${inv.id}/file`, inv.filename ?? "invoice"),
  exceptions: (status?: ExceptionStatus | null, openOnly = true) =>
    apiRequest<InvoiceException[]>(
      `${FP}/invoice-exceptions?open_only=${openOnly}${status ? `&status=${status}` : ""}`,
    ),
  decide: (exceptionId: string, body: DecisionIn) =>
    apiRequest<Invoice>(`${FP}/invoice-exceptions/${exceptionId}/decide`, { method: "POST", json: body }),
  creditNote: (exceptionId: string, amount: string, reference: string) =>
    apiRequest<Invoice>(`${FP}/invoice-exceptions/${exceptionId}/credit-note`, {
      method: "POST",
      json: { amount, reference },
    }),
  receipts: (poId: string) => apiRequest<Receipt[]>(`${FP}/purchase-orders/${poId}/receipts`),
  recordReceipt: (poId: string, receivedOn: string, lines: { po_line: number; quantity: string }[], notes: string) =>
    apiRequest<Receipt[]>(`${FP}/purchase-orders/${poId}/receipts`, {
      method: "POST",
      json: { received_on: receivedOn, lines, notes },
    }),
  nudge: (requestId: string) =>
    apiRequest<ReceiptRequest>(`${FP}/receipt-requests/${requestId}/nudge`, { method: "POST" }),
  measures: () => apiRequest<InvoiceMeasures>(`${FP}/measures/invoices`),
  receiptView: (token: string) => apiRequest<ReceiptPortalView>(`/receipt-confirm/${encodeURIComponent(token)}`),
  confirmReceipt: (token: string, receivedOn: string, lines: { po_line: number; quantity: string }[], notes: string) =>
    apiRequest<void>(`/receipt-confirm/${encodeURIComponent(token)}`, {
      method: "POST",
      json: { received_on: receivedOn, lines, notes },
    }),
}
