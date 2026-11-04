import { apiDownload, apiRequest } from "@/lib/api"

export type ApplicationStatus = "invited" | "needs_info" | "submitted" | "proposed" | "active" | "rejected"
export type ClientDocumentKind = "registration" | "tax" | "credit_report" | "trade_reference" | "other"
export type Risk = "low" | "medium" | "high"

export interface ClientCheck {
  key: string
  label: string
  status: "pass" | "fail" | "warn" | "unknown"
  detail: string
  clearable: boolean
  gap: string | null
}

export interface Contact {
  name: string
  email: string
  phone?: string
  role?: string
}

export interface CreditFactor {
  label: string
  value: string
  points: number
  max: number
}

export interface CreditProposal {
  score: number
  risk: Risk
  decision: "credit" | "deposit"
  credit_limit: string | null
  deposit_pct: string
  payment_terms: string
  currency: string
  factors: CreditFactor[]
  reasons: string[]
}

export interface ApplicationSummary {
  id: string
  reference: string
  status: ApplicationStatus
  client_name: string
  client_email: string
  invited_at: string | null
  submitted_at: string | null
  open_issues: number | null
  risk: Risk | null
  client_code: string | null
}

export interface Application extends ApplicationSummary {
  token_expires_at: string | null
  submissions: number
  legal_name: string | null
  tax_id: string | null
  country: string | null
  address: string | null
  phone: string | null
  website: string | null
  billing_email: string | null
  contacts: Contact[]
  currency: string | null
  requested_limit: string | null
  requested_terms: string | null
  expected_monthly: string | null
  years_trading: number | null
  extraction: { notes: string[]; documents: (Record<string, unknown> & { kind: ClientDocumentKind; filename: string; verified: boolean })[] } | null
  checks: ClientCheck[]
  cleared: { key: string; note: string; by: string; at: string }[]
  gaps: string[]
  agent_ran_at: string | null
  proposal: CreditProposal | null
  proposed_at: string | null
  decided_by_name: string | null
  decided_at: string | null
  decision_note: string | null
  changed_from_proposal: boolean
  client_id: string | null
  rejected_reason: string | null
  invited_by_name: string | null
  documents: { id: string; kind: ClientDocumentKind; filename: string; content_type: string; size: number; created_at: string }[]
  can_decide: string | null
  portal_url: string | null
}

export interface History {
  invoices: number
  paid: number
  on_time_rate: number | null
  avg_days_late: number | null
  overdue: number
  overdue_amount: string
  worst_overdue_days: number
  open_balance: string
  months: number
  peak_month: string
}

export interface Client {
  id: string
  code: string
  status: "active" | "on_hold"
  version: number
  name: string
  tax_id: string | null
  country: string | null
  address: string | null
  billing_email: string
  contacts: Contact[]
  currency: string
  credit_limit: string | null
  deposit_pct: string
  payment_terms: string
  risk: Risk | null
  erp_ref: string | null
  lab_ref: string | null
  synced_at: string | null
  sync: { in_sync: boolean; differences: string[] }
  last_reviewed_at: string | null
  next_review_on: string | null
  approved_by_name: string | null
  application_id: string | null
  history: History
  open_review_id: string | null
  created_at: string
}

export interface ReviewTerms {
  status: "active" | "on_hold"
  credit_limit: string | null
  deposit_pct: string
  payment_terms: string
}

export interface CreditReview {
  id: string
  reference: string
  client_id: string
  client_code: string
  client_name: string
  currency: string
  status: "proposed" | "approved" | "dismissed"
  trigger: "history" | "periodic"
  proposal: { metrics: History; current: ReviewTerms; proposed: ReviewTerms; reasons: string[] }
  decided_by_name: string | null
  decided_at: string | null
  decision_note: string | null
  created_at: string
}

export interface Terms {
  credit_limit: string | null
  deposit_pct: string
  payment_terms: string
  currency: string
}

export interface MonitorResult {
  reviewed: number
  proposed: number
  resynced: number
}

export interface ClientMeasures {
  applications: number
  accounts: number
  setup_days_median: number | null
  decision_days_median: number | null
  first_pass_clean: number
  first_pass_judged: number
  issues_caught: number
  gaps_sent: number
  sync_fixes: number
  controller_changes: number
  reviews_open: number
  reviews_approved: number
  reviews_dismissed: number
}

export interface ClientPortalView {
  client_name: string
  status: "open" | "used" | "expired"
  expires_at: string | null
  organisation: string
  gaps: string[]
  documents_held: ClientDocumentKind[]
  previous: Partial<Record<string, unknown>> & { contacts?: Contact[] }
}

const FP = "/finance-pod"
const A = (id: string) => `${FP}/client-applications/${id}`

export const clientsApi = {
  applications: () => apiRequest<ApplicationSummary[]>(`${FP}/client-applications`),
  application: (id: string) => apiRequest<Application>(A(id)),
  invite: (client_name: string, client_email: string) =>
    apiRequest<Application>(`${FP}/client-applications`, { method: "POST", json: { client_name, client_email } }),
  resend: (id: string) => apiRequest<Application>(`${A(id)}/resend`, { method: "POST" }),
  requestInfo: (id: string, reason: string) =>
    apiRequest<Application>(`${A(id)}/request-info`, { method: "POST", json: { reason } }),
  recheck: (id: string) => apiRequest<Application>(`${A(id)}/recheck`, { method: "POST" }),
  clear: (id: string, key: string, note: string) =>
    apiRequest<Application>(`${A(id)}/clear`, { method: "POST", json: { key, note } }),
  decide: (id: string, body: Terms & { note: string }) =>
    apiRequest<Application>(`${A(id)}/decide`, { method: "POST", json: body }),
  reject: (id: string, reason: string) => apiRequest<Application>(`${A(id)}/reject`, { method: "POST", json: { reason } }),
  downloadDocument: (id: string, doc: { id: string; filename: string }) =>
    apiDownload(`${A(id)}/documents/${doc.id}`, doc.filename),
  clients: () => apiRequest<Client[]>(`${FP}/clients`),
  client: (id: string) => apiRequest<Client>(`${FP}/clients/${id}`),
  sync: (id: string) => apiRequest<Client>(`${FP}/clients/${id}/sync`, { method: "POST" }),
  monitor: () => apiRequest<MonitorResult>(`${FP}/clients/monitor`, { method: "POST" }),
  importHistory: (file: File) => {
    const form = new FormData()
    form.append("file", file)
    return apiRequest<{ rows: number; clients: number; skipped: string[]; monitor: MonitorResult }>(`${FP}/clients/history`, {
      method: "POST",
      form,
    })
  },
  reviews: (openOnly: boolean) => apiRequest<CreditReview[]>(`${FP}/credit-reviews?open_only=${openOnly}`),
  decideReview: (id: string, body: { approve: boolean; terms?: Terms | null; status?: string | null; note: string }) =>
    apiRequest<CreditReview>(`${FP}/credit-reviews/${id}/decide`, { method: "POST", json: body }),
  measures: () => apiRequest<ClientMeasures>(`${FP}/measures/clients`),
  portal: (token: string) => apiRequest<ClientPortalView>(`/client-portal/${encodeURIComponent(token)}`),
  submitPortal: (token: string, form: FormData) =>
    apiRequest<void>(`/client-portal/${encodeURIComponent(token)}`, { method: "POST", form }),
}
