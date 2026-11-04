import { apiDownload, apiRequest } from "@/lib/api"

// --- 1.3 sourcing ----------------------------------------------------------------------

export type SourcingStatus = "open" | "awaiting_vendor" | "chosen"
export type QuoteStatus = "requested" | "received" | "declined"

export interface Candidate {
  vendor_code: string
  vendor_name: string
  vendor_email: string | null
  reasons: string[]
  contract_lines: number[]
  contract_total: string | null
  covers_all_lines: boolean
}

export interface Quote {
  id: string
  vendor_code: string | null
  vendor_name: string
  vendor_email: string | null
  status: QuoteStatus
  requested_at: string | null
  received_at: string | null
  total: string | null
  currency: string | null
  lead_time_days: number | null
  payment_terms: string | null
  valid_until: string | null
  notes: string | null
  filename: string | null
  ai_read: (Record<string, unknown> & { verified?: boolean }) | null
}

export interface ComparisonRow {
  option: "quote" | "contract"
  quote_id: string | null
  vendor_code: string | null
  vendor_name: string
  total: string
  vs_estimate: string
  lead_time_days: number | null
  arrives_by: string | null
  meets_needed_by: boolean | null
  payment_terms: string | null
  valid_until: string | null
  expired: boolean
  new_vendor: boolean
  flags: string[]
}

export interface SentEmail {
  id: string
  kind: "quote_request" | "portal_invite" | "purchase_order"
  to_email: string
  subject: string
  body: string
  status: "sent" | "failed" | "unknown"
  simulated: boolean
  error: string | null
  created_at: string
}

export interface Sourcing {
  status: SourcingStatus
  quotes_needed: number
  quotes_received: number
  candidates: Candidate[]
  quotes: Quote[]
  comparison: ComparisonRow[]
  chosen_quote_id: string | null
  chosen_vendor_code: string | null
  chosen_vendor_name: string | null
  chosen_total: string | null
  payment_terms: string | null
  delivery_date: string | null
  justification: string | null
  onboarding_id: string | null
  decided_at: string | null
  decided_by_name: string | null
  can_change: boolean
  emails: SentEmail[]
}

export interface VendorRef {
  vendor_code?: string | null
  vendor_name?: string | null
  vendor_email?: string | null
}

export interface QuoteIn {
  status: QuoteStatus
  total: string | null
  currency: string | null
  lead_time_days: number | null
  payment_terms: string | null
  valid_until: string | null
  notes: string | null
}

export interface ChooseIn {
  quote_id?: string | null
  contract_vendor_code?: string | null
  payment_terms: string
  delivery_date: string | null
  justification: string
}

// --- 1.5 onboarding --------------------------------------------------------------------

export type OnboardingStatus = "invited" | "submitted" | "verified" | "active" | "rejected"

export interface Check {
  key: string
  label: string
  status: "pass" | "fail" | "warn" | "unknown"
  detail: string
  clearable: boolean
}

export interface OnboardingSummary {
  id: string
  kind: "new_vendor" | "bank_change"
  status: OnboardingStatus
  vendor_name: string
  vendor_email: string
  vendor_code: string | null
  request_id: string | null
  request_reference: string | null
  invited_at: string | null
  submitted_at: string | null
  open_issues: number | null
}

export interface Onboarding extends OnboardingSummary {
  token_expires_at: string | null
  legal_name: string | null
  tax_id: string | null
  tax_form: string | null
  address: string | null
  phone: string | null
  bank_name: string | null
  account_name: string | null
  routing_masked: string | null
  account_masked: string | null
  extraction: Record<string, unknown> | null
  checks: Check[]
  cleared: { key: string; note: string; by: string; at: string }[]
  agent_ran_at: string | null
  callback_phone: string | null
  callback_source: string | null
  callback_contact: string | null
  callback_notes: string | null
  verified_by_name: string | null
  verified_at: string | null
  activated_by_name: string | null
  activated_at: string | null
  erp_ref: string | null
  rejected_reason: string | null
  documents: { id: string; kind: string; filename: string; content_type: string; size: number; created_at: string }[]
  can_verify: string | null
  can_activate: string | null
  portal_url: string | null
}

export interface CallbackIn {
  phone: string
  source: string
  contact: string
  confirmed_last4: string
  notes: string
}

export const CALLBACK_SOURCES = [
  "vendor master / earlier records",
  "vendor's official website",
  "public directory",
  "contract or purchase history",
  "other independent source",
]

export interface SanctionsInfo {
  entries: number
  loaded_at: string | null
  source_url: string
}

export interface PortalView {
  vendor_name: string
  kind: "new_vendor" | "bank_change"
  status: "open" | "used" | "expired"
  expires_at: string | null
  organisation: string
}

// --- 1.6 purchase orders ------------------------------------------------------------------

export type PoStatus = "draft" | "pending_approval" | "approved" | "issued" | "acknowledged" | "cancelled"

export interface PoLine {
  description: string
  quantity: string
  unit: string | null
  unit_price: string
  category: string | null
  catalogue_item_code: string | null
  price_source: string
  amount: string
}

export interface PurchaseOrder {
  id: string
  reference: string
  request_id: string
  request_reference: string
  status: PoStatus
  version: number
  vendor_code: string
  vendor_name: string
  vendor_email: string | null
  currency: string
  total: string
  quote_total: string | null
  payment_terms: string | null
  delivery_date: string | null
  cost_centre_code: string | null
  lab_code: string | null
  project_code: string | null
  grant_code: string | null
  notes: string | null
  lines: PoLine[]
  issues: { message: string; blocking: boolean }[]
  drafted_by_name: string
  approval_capacity: string | null
  approver_email: string | null
  approved_by_name: string | null
  approved_at: string | null
  approval_acting_for: string | null
  self_approval: boolean
  issued_at: string | null
  erp_system: string | null
  erp_ref: string | null
  acknowledged_at: string | null
  acknowledgement_note: string | null
  acknowledgement_filename: string | null
  cancelled_reason: string | null
  created_at: string
  can_approve: string | null
}

export interface PoSummary {
  id: string
  reference: string
  request_id: string
  request_reference: string
  status: PoStatus
  vendor_name: string
  total: string
  currency: string
  issued_at: string | null
  created_at: string
}

export interface PoUpdate {
  lines: { description: string; quantity: string; unit: string | null; unit_price: string; category: string | null }[]
  payment_terms: string | null
  delivery_date: string | null
  notes: string | null
}

// --- measures ------------------------------------------------------------------------------

export interface Duration {
  label: string
  median_days: number | null
  count: number
}

export interface Measures {
  cycle: Duration
  stages: Duration[]
  submitted: number
  reworked: number
  rework_rate: number | null
  rejected: number
  waiting: { stage: string; count: number; oldest_days: number | null }[]
  months: { month: string; pos_issued: number; median_cycle_days: number | null }[]
}

const FP = "/finance-pod"
const S = (id: string) => `${FP}/requests/${id}/sourcing`

export const procurementApi = {
  sourcing: (requestId: string) => apiRequest<Sourcing>(S(requestId)),
  refreshSourcing: (requestId: string) => apiRequest<Sourcing>(`${S(requestId)}/refresh`, { method: "POST" }),
  requestQuotes: (requestId: string, vendors: VendorRef[], replyBy: string, message: string) =>
    apiRequest<Sourcing>(`${S(requestId)}/quote-requests`, {
      method: "POST",
      json: { vendors, reply_by: replyBy, message },
    }),
  addQuote: (requestId: string, body: VendorRef & QuoteIn) =>
    apiRequest<Sourcing>(`${S(requestId)}/quotes`, { method: "POST", json: body }),
  updateQuote: (requestId: string, quoteId: string, body: QuoteIn) =>
    apiRequest<Sourcing>(`${S(requestId)}/quotes/${quoteId}`, { method: "PUT", json: body }),
  attachQuote: (requestId: string, quoteId: string, file: File) => {
    const form = new FormData()
    form.append("file", file)
    return apiRequest<Sourcing>(`${S(requestId)}/quotes/${quoteId}/file`, { method: "POST", form })
  },
  downloadQuote: (requestId: string, quote: Quote) =>
    apiDownload(`${S(requestId)}/quotes/${quote.id}/file`, quote.filename ?? "quote"),
  choose: (requestId: string, body: ChooseIn) =>
    apiRequest<Sourcing>(`${S(requestId)}/choose`, { method: "POST", json: body }),

  onboardings: () => apiRequest<OnboardingSummary[]>(`${FP}/onboardings`),
  onboarding: (id: string) => apiRequest<Onboarding>(`${FP}/onboardings/${id}`),
  invite: (vendorName: string, vendorEmail: string) =>
    apiRequest<Onboarding>(`${FP}/onboardings`, {
      method: "POST",
      json: { vendor_name: vendorName, vendor_email: vendorEmail },
    }),
  bankChange: (vendorCode: string, vendorEmail: string | null) =>
    apiRequest<Onboarding>(`${FP}/onboardings/bank-change`, {
      method: "POST",
      json: { vendor_code: vendorCode, vendor_email: vendorEmail || null },
    }),
  resend: (id: string) => apiRequest<Onboarding>(`${FP}/onboardings/${id}/resend`, { method: "POST" }),
  requestResubmission: (id: string, reason: string) =>
    apiRequest<Onboarding>(`${FP}/onboardings/${id}/resubmission`, { method: "POST", json: { reason } }),
  recheck: (id: string) => apiRequest<Onboarding>(`${FP}/onboardings/${id}/recheck`, { method: "POST" }),
  clear: (id: string, key: string, note: string) =>
    apiRequest<Onboarding>(`${FP}/onboardings/${id}/clear`, { method: "POST", json: { key, note } }),
  verify: (id: string, body: CallbackIn) =>
    apiRequest<Onboarding>(`${FP}/onboardings/${id}/verify`, { method: "POST", json: body }),
  activate: (id: string) => apiRequest<Onboarding>(`${FP}/onboardings/${id}/activate`, { method: "POST" }),
  reject: (id: string, reason: string) =>
    apiRequest<Onboarding>(`${FP}/onboardings/${id}/reject`, { method: "POST", json: { reason } }),
  downloadDocument: (id: string, doc: { id: string; filename: string }) =>
    apiDownload(`${FP}/onboardings/${id}/documents/${doc.id}`, doc.filename),
  sanctions: () => apiRequest<SanctionsInfo>(`${FP}/onboardings/sanctions`),
  refreshSanctions: (file?: File) => {
    const form = new FormData()
    if (file) form.append("file", file)
    return apiRequest<SanctionsInfo>(`${FP}/onboardings/sanctions/refresh`, { method: "POST", form })
  },

  portal: (token: string) => apiRequest<PortalView>(`/vendor-portal/${encodeURIComponent(token)}`),
  submitPortal: (token: string, form: FormData) =>
    apiRequest<void>(`/vendor-portal/${encodeURIComponent(token)}`, { method: "POST", form }),

  purchaseOrders: (status?: PoStatus | null) =>
    apiRequest<PoSummary[]>(status ? `${FP}/purchase-orders?status=${status}` : `${FP}/purchase-orders`),
  requestPo: (requestId: string) => apiRequest<PurchaseOrder | null>(`${FP}/requests/${requestId}/po`),
  draftPo: (requestId: string) => apiRequest<PurchaseOrder>(`${FP}/requests/${requestId}/po`, { method: "POST" }),
  updatePo: (id: string, version: number, body: PoUpdate) =>
    apiRequest<PurchaseOrder>(`${FP}/purchase-orders/${id}`, {
      method: "PUT",
      json: { ...body, expected_version: version },
    }),
  poAction: (id: string, action: "confirm" | "approve" | "issue", version: number) =>
    apiRequest<PurchaseOrder>(`${FP}/purchase-orders/${id}/${action}`, {
      method: "POST",
      json: { expected_version: version },
    }),
  cancelPo: (id: string, version: number, reason: string) =>
    apiRequest<PurchaseOrder>(`${FP}/purchase-orders/${id}/cancel`, {
      method: "POST",
      json: { expected_version: version, reason },
    }),
  acknowledgePo: (id: string, version: number, note: string, receivedOn: string | null, file: File | null) => {
    const form = new FormData()
    form.append("expected_version", String(version))
    form.append("note", note)
    if (receivedOn) form.append("received_on", receivedOn)
    if (file) form.append("file", file)
    return apiRequest<PurchaseOrder>(`${FP}/purchase-orders/${id}/acknowledge`, { method: "POST", form })
  },

  measures: () => apiRequest<Measures>(`${FP}/measures`),
}
