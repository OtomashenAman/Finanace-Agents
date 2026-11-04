import { apiDownload, apiRequest } from "@/lib/api"

export type RequestStatus = "draft" | "submitted" | "queried" | "approved" | "ordered" | "rejected" | "cancelled"
export type CodingSource = "requester" | "agent"
export type RequestFileKind = "quote" | "specification" | "other"
export type PriceStatus = "matches" | "above_contract" | "below_contract" | "no_estimate" | "no_match"

export interface FinanceSettings {
  currency: string
  purchasing_threshold: string
  min_quotes: number
  allow_self_approval: boolean
  price_tolerance_pct: string
  price_tolerance_amount: string
  qty_tolerance_pct: string
  payment_horizon_days: number
  cash_available: string | null // null: the run isn't checked against cash
  unusual_payment_amount: string
  bank_change_days: number
  max_new_client_limit: string
  credit_review_days: number
  updated_at: string | null
}

export type FinanceSettingsUpdate = Omit<FinanceSettings, "updated_at"> & { clear_cash_available?: boolean }

export interface CostCentre {
  code: string
  name: string
  owner_email: string | null
  active: boolean
}

export interface Lab {
  code: string
  name: string
  cost_centre_code: string | null
  active: boolean
}

export interface Project extends Lab {
  grant_code: string | null
}

export interface Grant {
  code: string
  name: string
  sponsor: string | null
  cost_centre_code: string | null
  owner_email: string | null
  start_date: string | null
  end_date: string | null
  award_amount: string | null
  unallowable_categories: string[]
  active: boolean
}

export interface Budget {
  fiscal_year: number
  cost_centre_code: string | null
  grant_code: string | null
  category: string | null
  amount: string
  committed: string
  spent: string
  remaining: string
}

export interface CatalogueItem {
  item_code: string
  description: string
  category: string | null
  unit: string | null
  unit_price: string
  vendor_code: string | null
  contract_ref: string | null
  contract_end: string | null
  active: boolean
}

export interface Vendor {
  code: string
  name: string
  email: string | null
  tax_id: string | null
  status: string
  categories: string[]
}

export interface AuthorityTier {
  scope: "request" | "po"
  cost_centre_code: string | null
  min_amount: string
  approver_email: string
  capacity: string
}

export interface Reference {
  cost_centres: CostCentre[]
  labs: Lab[]
  projects: Project[]
  grants: Grant[]
  budgets: Budget[]
  catalogue: CatalogueItem[]
  vendors: Vendor[]
  authority: AuthorityTier[]
}

export interface ImportResult {
  sheets: { sheet: string; title: string; created: number; updated: number; removed: number }[]
  warnings: string[]
}

export interface Overview {
  requests: Partial<Record<RequestStatus, number>>
  reference: Record<string, number>
  waiting_for_me: number
  pos_waiting_for_me: number
  onboarding_open: number
  invoices: Partial<Record<string, number>>
  exceptions_open: Partial<Record<string, number>>
  payment_runs: Partial<Record<string, number>>
  queries: Partial<Record<string, number>>
  client_applications: Partial<Record<string, number>>
  credit_reviews_open: number
}

export interface LineIn {
  description: string
  quantity: string
  unit: string | null
  unit_price: string | null
  category: string | null
  catalogue_item_code: string | null
}

export interface Line extends LineIn {
  amount: string
}

export interface RequestIn {
  title: string
  purpose: string
  needed_by: string | null
  cost_centre_code: string | null
  lab_code: string | null
  project_code: string | null
  grant_code: string | null
  lines: LineIn[]
  source_text?: string | null
}

export interface RequestFile {
  id: string
  kind: RequestFileKind
  filename: string
  content_type: string
  size: number
  created_at: string
}

export interface Problem {
  field: string
  message: string
  blocking: boolean
}

export interface PriceCheck {
  line: number
  status: PriceStatus
  item_code: string | null
  item_description: string | null
  contract_price: string | null
  vendor_code: string | null
  vendor_name: string | null
  contract_ref: string | null
  difference: string | null
  how: "item_code" | "description" | null
}

export interface CodingSuggestion {
  cost_centre_code: string | null
  lab_code: string | null
  project_code: string | null
  grant_code: string | null
  line_categories: (string | null)[]
  reason: string
  source: "ai" | "history"
  provenance: Record<string, string | null> | null
}

export interface Enrichment {
  ran_at: string
  suggestion: CodingSuggestion | null
  suggestion_note: string | null
  price_checks: PriceCheck[]
  problems: Problem[]
  quotes_needed: number
}

export interface RequestSummary {
  id: string
  reference: string
  title: string
  status: RequestStatus
  requester_id: string
  requester_name: string
  total: string
  currency: string
  cost_centre_code: string | null
  needed_by: string | null
  submitted_at: string | null
  created_at: string
  updated_at: string
  blocking_problems: number | null
}

export type Decision = "approve" | "reject" | "query"

export interface BudgetImpact {
  budget_id: string | null
  holder: string
  fiscal_year: number
  category: string | null
  lines: number[]
  budget: string
  committed: string
  spent: string
  approved_requests: string
  available: string
  this_request: string
  remaining_after: string
  over_budget: boolean
}

export interface Finding {
  kind: "over_budget" | "no_budget" | "unallowable" | "grant_period" | "uncategorised" | "routing"
  message: string
  severity: "blocking" | "acknowledge" | "info"
}

export interface RouteStep {
  step: number
  capacity: string
  approver_email: string | null
  approver_name: string | null
  min_amount: string
  status: "waiting" | "approved" | "rejected" | "queried" | "pending"
}

export interface BudgetCheck {
  ran_at: string
  round: number
  total: string
  currency: string
  fiscal_year: number
  impacts: BudgetImpact[]
  findings: Finding[]
  route: RouteStep[]
}

export interface DecisionRecord {
  id: string
  round: number
  step: number
  capacity: string
  approver_email: string | null
  decided_by_name: string
  decision: Decision
  note: string
  acting_for: string | null
  budget_acknowledged: boolean
  self_approval: boolean
  created_at: string
}

export interface PurchaseRequest extends RequestSummary {
  round: number
  budget_check: BudgetCheck | null
  route: RouteStep[]
  current_step: RouteStep | null
  can_decide: boolean
  decide_blocker: string | null
  decisions: DecisionRecord[]
  version: number
  purpose: string
  lab_code: string | null
  project_code: string | null
  grant_code: string | null
  coding_source: CodingSource | null
  source_text: string | null
  lines: Line[]
  files: RequestFile[]
  enrichment: Enrichment | null
  closed_at: string | null
  can_edit: boolean
}

export interface RequestDraft {
  title: string
  purpose: string
  needed_by: string | null
  lines: { description: string; quantity: string; unit: string | null; unit_price: string | null }[]
  notes: string[]
  provenance: Record<string, string | null>
}

const BASE = "/finance-pod"
const R = `${BASE}/requests`

export const fpodApi = {
  overview: () => apiRequest<Overview>(`${BASE}/overview`),
  settings: () => apiRequest<FinanceSettings>(`${BASE}/settings`),
  saveSettings: (body: FinanceSettingsUpdate) =>
    apiRequest<FinanceSettings>(`${BASE}/settings`, { method: "PUT", json: body }),
  reference: () => apiRequest<Reference>(`${BASE}/reference`),
  downloadTemplate: () => apiDownload(`${BASE}/reference/template`, "finance-pod-reference.xlsx"),
  importReference: (file: File) => {
    const form = new FormData()
    form.append("file", file)
    return apiRequest<ImportResult>(`${BASE}/reference/workbook`, { method: "POST", form })
  },
  requests: (filters: { status?: RequestStatus | null; mine?: boolean }) => {
    const q = new URLSearchParams()
    if (filters.status) q.set("status", filters.status)
    if (filters.mine) q.set("mine", "true")
    const s = q.toString()
    return apiRequest<RequestSummary[]>(s ? `${R}?${s}` : R)
  },
  request: (id: string) => apiRequest<PurchaseRequest>(`${R}/${id}`),
  create: (body: RequestIn) => apiRequest<PurchaseRequest>(R, { method: "POST", json: body }),
  update: (id: string, body: RequestIn, version: number) =>
    apiRequest<PurchaseRequest>(`${R}/${id}`, { method: "PUT", json: { ...body, expected_version: version } }),
  draftFromText: (text: string) =>
    apiRequest<RequestDraft>(`${R}/draft-from-text`, { method: "POST", json: { text } }),
  suggest: (id: string) => apiRequest<PurchaseRequest>(`${R}/${id}/suggest`, { method: "POST" }),
  acceptSuggestion: (id: string, version: number) =>
    apiRequest<PurchaseRequest>(`${R}/${id}/accept-suggestion`, {
      method: "POST",
      json: { expected_version: version },
    }),
  submit: (id: string, version: number) =>
    apiRequest<PurchaseRequest>(`${R}/${id}/submit`, { method: "POST", json: { expected_version: version } }),
  cancel: (id: string, version: number, reason: string) =>
    apiRequest<PurchaseRequest>(`${R}/${id}/cancel`, {
      method: "POST",
      json: { expected_version: version, reason },
    }),
  approvals: () => apiRequest<RequestSummary[]>(`${BASE}/approvals`),
  decide: (id: string, version: number, decision: Decision, note: string, acknowledgeBudget: boolean) =>
    apiRequest<PurchaseRequest>(`${R}/${id}/decide`, {
      method: "POST",
      json: { expected_version: version, decision, note, acknowledge_budget: acknowledgeBudget },
    }),
  recheckBudget: (id: string) => apiRequest<PurchaseRequest>(`${R}/${id}/budget-check`, { method: "POST" }),
  uploadFile: (id: string, file: File, kind: RequestFileKind) => {
    const form = new FormData()
    form.append("file", file)
    form.append("kind", kind)
    return apiRequest<PurchaseRequest>(`${R}/${id}/files`, { method: "POST", form })
  },
  removeFile: (id: string, fileId: string) =>
    apiRequest<PurchaseRequest>(`${R}/${id}/files/${fileId}`, { method: "DELETE" }),
  downloadFile: (id: string, file: RequestFile) => apiDownload(`${R}/${id}/files/${file.id}`, file.filename),
}
