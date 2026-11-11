import { apiDownload, apiRequest } from "@/lib/api"

export type SubmissionStatus = "in_lab" | "report_issued" | "invoiced" | "cancelled"
export type SalesInvoiceStatus = "review" | "approved" | "sent" | "void"
export type Turnaround = "standard" | "express" | "rush"

export interface BillingFlag {
  key: string
  label: string
  detail: string
  cleared?: { by: string; note: string; at: string }
}

export interface SubmissionLineIn {
  item_ref: string
  stone_type: string
  carat: string | null
  service_code: string
  quantity: number
  special_price?: string | null
  special_reason?: string | null
}

export interface SubmissionIn {
  client_code: string
  turnaround: Turnaround
  estimate: string | null
  notes: string | null
  lines: SubmissionLineIn[]
}

export interface Submission {
  id: string
  reference: string
  external_ref: string | null
  client_code: string
  client_name: string | null
  status: SubmissionStatus
  turnaround: Turnaround
  received_on: string
  estimate: string | null
  notes: string | null
  report_issued_at: string | null
  issued_via: string | null
  lines: (SubmissionLineIn & { id: string; position: number; requested: boolean; performed: boolean })[]
  invoice_id: string | null
  invoice_reference: string | null
  created_at: string
}

export interface PerformedIn {
  item_ref: string
  service_code: string
  stone_type?: string | null
  carat?: string | null
  quantity?: number
}

export interface SalesInvoiceSummary {
  id: string
  reference: string
  status: SalesInvoiceStatus
  client_code: string
  client_name: string
  submission_reference: string
  currency: string
  total: string
  estimate: string | null
  open_items: string[]
  built_at: string
  sent_at: string | null
}

export interface SalesInvoiceLine {
  id: string
  position: number
  item_ref: string
  service_code: string
  description: string
  stone_type: string
  carat: string | null
  quantity: number
  list_price: string | null
  unit_price: string
  price_source: "schedule" | "contract" | "override" | "none"
  price_note: string | null
  amount: string
  flags: BillingFlag[]
  override_price: string | null
  override_reason: string | null
  override_status: "pending" | "approved" | "rejected" | null
  override_by_name: string | null
  override_decided_by_name: string | null
}

export interface SalesInvoice extends SalesInvoiceSummary {
  version: number
  submission_id: string
  client_id: string
  bill_to_email: string
  payment_terms: string
  deposit_pct: string
  subtotal: string
  discount_total: string
  tax_name: string | null
  tax_rate: string
  tax: string
  flags: BillingFlag[]
  lines: SalesInvoiceLine[]
  flagged_on_build: boolean
  corrected: boolean
  approved_by_name: string | null
  approved_at: string | null
  issue_date: string | null
  due_date: string | null
  erp_ref: string | null
  viewed_at: string | null
  void_reason: string | null
  report_issued_at: string | null
}

export interface FeeSchedule {
  fees: { service_code: string; service_name: string; stone_type: string | null; carat_from: string | null; carat_to: string | null; turnaround: string; fee: string; currency: string }[]
  contracts: { client_code: string; service_code: string; price: string | null; discount_pct: string | null; contract_ref: string | null; valid_to: string | null }[]
  taxes: { country: string; region: string | null; name: string; rate_pct: string }[]
}

export interface BillingMeasures {
  sent: number
  accurate: number
  straight_through: number
  days_to_invoice_median: number | null
  same_day: number
  in_review: number
  overrides_approved: number
  overrides_rejected: number
  statements: number
}

export interface Statement {
  client_code: string
  period: string
  open_balance: string
  open_invoices: number
  created_at: string
}

export interface PublicInvoice {
  organisation: string
  reference: string
  client_name: string
  client_code: string
  submission_reference: string
  issue_date: string | null
  due_date: string | null
  payment_terms: string
  currency: string
  lines: { item_ref: string; description: string; stone_type: string; carat: string | null; quantity: number; unit_price: string; amount: string }[]
  subtotal: string
  discount_total: string
  tax_name: string | null
  tax_rate: string
  tax: string
  total: string
  status: "open" | "void"
}

const FP = "/finance-pod"
const SI = (id: string) => `${FP}/sales-invoices/${id}`

export const billingApi = {
  submissions: (status: SubmissionStatus | null) =>
    apiRequest<Submission[]>(status ? `${FP}/lab-submissions?status=${status}` : `${FP}/lab-submissions`),
  createSubmission: (body: SubmissionIn) => apiRequest<Submission>(`${FP}/lab-submissions`, { method: "POST", json: body }),
  importSubmissions: (file: File) => {
    const form = new FormData()
    form.append("file", file)
    return apiRequest<{ submissions: number; issued: number; errors: string[] }>(`${FP}/lab-submissions/import`, {
      method: "POST",
      form,
    })
  },
  reportIssued: (id: string, performed: PerformedIn[] | null) =>
    apiRequest<SalesInvoice>(`${FP}/lab-submissions/${id}/report-issued`, { method: "POST", json: { performed } }),
  cancelSubmission: (id: string, reason: string) =>
    apiRequest<Submission>(`${FP}/lab-submissions/${id}/cancel`, { method: "POST", json: { reason } }),
  invoices: (status: SalesInvoiceStatus | null) =>
    apiRequest<SalesInvoiceSummary[]>(status ? `${FP}/sales-invoices?status=${status}` : `${FP}/sales-invoices`),
  invoice: (id: string) => apiRequest<SalesInvoice>(SI(id)),
  downloadPdf: (inv: { id: string; reference: string }) => apiDownload(`${SI(inv.id)}/pdf`, `${inv.reference}.pdf`),
  proposeOverride: (id: string, line_id: string, price: string, reason: string) =>
    apiRequest<SalesInvoice>(`${SI(id)}/override`, { method: "POST", json: { line_id, price, reason } }),
  decideOverride: (id: string, line_id: string, approve: boolean, note: string) =>
    apiRequest<SalesInvoice>(`${SI(id)}/override/decide`, { method: "POST", json: { line_id, approve, note } }),
  clearFlag: (id: string, line_id: string | null, key: string, note: string) =>
    apiRequest<SalesInvoice>(`${SI(id)}/clear`, { method: "POST", json: { line_id, key, note } }),
  approve: (id: string) => apiRequest<SalesInvoice>(`${SI(id)}/approve`, { method: "POST" }),
  void: (id: string, reason: string) => apiRequest<SalesInvoice>(`${SI(id)}/void`, { method: "POST", json: { reason } }),
  feeSchedule: () => apiRequest<FeeSchedule>(`${FP}/fee-schedule`),
  uploadFeeSchedule: (file: File) => {
    const form = new FormData()
    form.append("file", file)
    return apiRequest<FeeSchedule>(`${FP}/fee-schedule`, { method: "POST", form })
  },
  downloadTemplate: () => apiDownload(`${FP}/fee-schedule/template`, "fee-schedule.xlsx"),
  statements: () => apiRequest<Statement[]>(`${FP}/statements`),
  sendStatements: () => apiRequest<{ period: string; sent: number; already_sent: number }>(`${FP}/statements/send`, { method: "POST" }),
  measures: () => apiRequest<BillingMeasures>(`${FP}/measures/billing`),
  publicInvoice: (token: string) => apiRequest<PublicInvoice>(`/client-invoice/${encodeURIComponent(token)}`),
  publicPdf: (token: string, reference: string) => apiDownload(`/client-invoice/${encodeURIComponent(token)}/pdf`, `${reference}.pdf`),
}
