import type { Artifact, Message, PostingTask, Snapshot } from "@/features/service-pod/api"
import { apiRequest } from "@/lib/api"

/** Finance POD: the AP / AR agents of the GIA requirement on the shared case engine.
 *  Its own API (/finance/...): only its cases, behind the viewer's capacities. */

export type FinanceCapacity =
  | "requester"
  | "budget_owner"
  | "buyer"
  | "receiver"
  | "ap_analyst"
  | "vendor_approver"
  | "grants_accountant"
  | "controller"
  | "treasury"
  | "credit_controller"
  | "billing_analyst"
  | "cash_team"
  | "finance_lead"

export type StepKind = "agent" | "person" | "system" | "manual"
export type StepStatus = "pending" | "done" | "not_applicable" | "failed"
export type CaseStatus = "draft" | "approved" | "completed" | "cancelled"

export interface EntityRef {
  id: string
  code: string
  name: string
}

export interface CapacityInfo {
  key: FinanceCapacity
  label: string
  description: string
}

export interface FinanceMe {
  is_admin: boolean
  capacities: { capacity: FinanceCapacity; label: string; entities: EntityRef[] | null }[]
  can_open: string[]
}

export interface Assignment {
  id: string
  user: { id: string; name: string; email: string }
  capacity: FinanceCapacity
  label: string
  entity: EntityRef | null
  granted_by: string | null
  created_at: string
}

export interface FinanceWorkflow {
  key: string
  name: string
  prefix: string
  description: string
  signoffs: string[]
}

export interface Measure {
  id: string
  label: string
  unit: string
  value: string | null
}

export type AiKind = "agent_step" | "posted" | "verified"

export interface FinanceAiEvent {
  at: string
  kind: AiKind
  summary: string
  case_id: string | null
  reference: string | null
}

export interface FinanceKpis {
  open_ap: number
  open_ar: number
  erp_pending: number
  overdue_receivables: string | null
  overdue_clients: number
  currency: string | null
  last_snapshot_at: string | null
  source_name: string | null
}

export interface WorkflowTile {
  area: "AP" | "AR"
  key: string
  name: string
  prefix: string
  description: string
  open: number
  approved: number
  completed_30d: number
  measures: Measure[]
}

export type QueueType = "decide" | "run" | "mail" | "post" | "verify" | "review"

export interface QueueItem {
  type: QueueType
  case_id: string
  reference: string
  workflow: string
  case_title: string
  step_key: string
  step_title: string
  kind: StepKind | null
  waiting_since: string
}

export interface FinanceDashboard {
  kpis: FinanceKpis | null
  ai: { last_7_days: Record<AiKind, number>; recent: FinanceAiEvent[] } | null
  workflows: WorkflowTile[]
  my_queue: QueueItem[]
}

export interface JsonSchema {
  type?: string
  title?: string
  description?: string
  properties?: Record<string, JsonSchema>
  required?: string[]
  enum?: (string | number)[]
  anyOf?: JsonSchema[]
  default?: unknown
  maxLength?: number
  format?: string
  const?: unknown
  $ref?: string
  $defs?: Record<string, JsonSchema>
  items?: JsonSchema
  examples?: unknown[]
  minimum?: number
  maximum?: number
  maxItems?: number
  /** Option labels for an enum, in words */
  "x-labels"?: Record<string, string>
  /** A field naming a document of the case: the document kinds it takes */
  "x-document"?: string[]
}

export interface L5 {
  code: string
  text: string
  status: StepStatus
  result: Record<string, unknown> | null
  note: string | null
  done_by: string | null
  done_at: string | null
  result_schema: JsonSchema
  /** What was filled in before the step was sent back */
  previous?: Record<string, unknown> | null
}

export interface Step {
  key: string
  l4: string
  title: string
  kind: StepKind
  capacity: string | null
  after: string[]
  status: StepStatus
  blocked: string | null
  /** An agent step that won't run until something is fixed (in an earlier step, or e.g. a
   *  document to upload) */
  needs?: { message: string; fix_step: string | null; fix_title: string | null } | null
  l5: L5[]
}

export interface PersonRef {
  id: string
  name: string
}

export interface CaseSummary {
  id: string
  reference: string
  workflow: string
  title: string
  status: CaseStatus
  stage: string | null
  version: number
  entity: EntityRef
  owner: PersonRef
  is_demo: boolean
  open_review_tasks: number
  created_at: string
  updated_at: string
}

export interface Approval {
  id: string
  user: PersonRef
  capacity: string
  valid: boolean
  created_at: string
}

export interface ReviewTask {
  id: string
  kind: string
  subject: string | null
  detail: string
  blocking: boolean
  status: "open" | "resolved"
  resolution: string | null
  created_at: string
}

export interface CaseDetail extends CaseSummary {
  snapshot_id: string
  messages: Message[]
  artifacts: Artifact[]
  posting_tasks: PostingTask[]
  selection: Record<string, unknown>
  state: Record<string, unknown>
  fingerprint: string
  approvals: Approval[]
  review_tasks: ReviewTask[]
  blockers: string[]
  completion_blockers: string[]
  next_signoff: string | null
  allowed_actions: Record<string, string | null>
  steps: Step[]
}

export interface CaseAction {
  id: string
  version: number
  action: string
  payload?: Record<string, unknown>
}

export interface CatalogueEntry {
  id: string
  name: string
  detail: string | null
}

export interface Catalogue {
  currency: string
  items: { code: string; name: string; group: string; catalogue_rate: string | null; contract_rates: Record<string, string> }[]
  vendors: CatalogueEntry[]
  cost_centres: CatalogueEntry[]
  labs: CatalogueEntry[]
  grants: CatalogueEntry[]
  purchase_requests: CatalogueEntry[]
  incoming_invoices: CatalogueEntry[]
  billable_submissions: CatalogueEntry[]
  /** Month-end close: months already closed (id YYYY-MM, name the case) */
  closed_periods: CatalogueEntry[]
  /** The last month this snapshot can close */
  closable_until: string | null
  /** Why the list to pick from is empty, in words */
  empty_reason: string | null
}

export interface SanctionsStatus {
  loaded: boolean
  list_name: string | null
  entries: number
  loaded_at: string | null
  source_url: string | null
}

export interface PortalView {
  vendor_name: string
  expires_at: string
  required: string[]
  optional: string[]
  uploaded: { kind: string; filename: string; uploaded_at: string }[]
}

const base = "/finance"

/** Who holds a step's capacity for the case's entity (a Finance Admin testing the workflow) */
export interface StepPerson {
  id: string
  full_name: string
  email: string
  /** segregation of duties: why they can't do this step (null: they can) */
  blocked: string | null
}

export const financeApi = {
  me: () => apiRequest<FinanceMe>(`${base}/me`),
  dashboard: () => apiRequest<FinanceDashboard>(`${base}/dashboard`),
  workflows: () => apiRequest<FinanceWorkflow[]>(`${base}/workflows`),
  cases: (filters: { workflow?: string | null; status?: string | null }) => {
    const params = new URLSearchParams()
    if (filters.workflow) params.set("workflow", filters.workflow)
    if (filters.status) params.set("status", filters.status)
    const qs = params.toString()
    return apiRequest<CaseSummary[]>(`${base}/cases${qs ? `?${qs}` : ""}`)
  },
  case: (id: string) => apiRequest<CaseDetail>(`${base}/cases/${encodeURIComponent(id)}`),
  act: ({ id, version, action, payload = {} }: CaseAction) =>
    apiRequest<CaseDetail>(`${base}/cases/${encodeURIComponent(id)}/actions`, {
      method: "POST",
      json: { action, expected_version: version, payload },
    }),
  open: (body: { workflow: string; snapshot_id: string; title: string; selection: Record<string, unknown> }) =>
    apiRequest<CaseDetail>(`${base}/cases`, { method: "POST", json: body }),
  sources: (workflow: string) => apiRequest<Snapshot[]>(`${base}/sources?workflow=${encodeURIComponent(workflow)}`),
  caseSources: (caseId: string) => apiRequest<Snapshot[]>(`${base}/cases/${caseId}/sources`),
  sourceCatalogue: (snapshotId: string, workflow: string) =>
    apiRequest<Catalogue>(`${base}/sources/${snapshotId}/catalogue?workflow=${encodeURIComponent(workflow)}`),
  stepPeople: (caseId: string, by: { step?: string; capacity?: string }) =>
    apiRequest<StepPerson[]>(`${base}/cases/${caseId}/people?${new URLSearchParams(by as Record<string, string>)}`),
  caseCatalogue: (caseId: string) => apiRequest<Catalogue>(`${base}/cases/${caseId}/catalogue`),
  upload: ({ caseId, kind, file }: { caseId: string; kind: string; file: File }) => {
    const form = new FormData()
    form.append("file", file)
    form.append("kind", kind)
    return apiRequest<Artifact>(`${base}/cases/${caseId}/artifacts`, { method: "POST", form })
  },
  documentUrl: (id: string) => `${base}/artifacts/${id}/content`,
  sendMessage: ({ id, version }: { id: string; version: number }) =>
    apiRequest<Message>(`${base}/messages/${id}/send`, {
      method: "POST",
      json: { expected_version: version, checks: { recipient: true, mapping: true, tone: true } },
    }),
  taskAction: ({ id, version, action, snapshotId }: { id: string; version: number; action: string; snapshotId?: string }) =>
    apiRequest<PostingTask>(`${base}/tasks/${id}/actions`, {
      method: "POST",
      json: { action, expected_version: version, ...(snapshotId ? { snapshot_id: snapshotId } : {}) },
    }),
  intake: (snapshotId: string) =>
    apiRequest<{ opened: string[]; already: number }>(`${base}/apm/intake`, {
      method: "POST",
      json: { snapshot_id: snapshotId },
    }),
  billingIntake: (snapshotId: string) =>
    apiRequest<{ opened: string[]; already: number }>(`${base}/arb/intake`, {
      method: "POST",
      json: { snapshot_id: snapshotId },
    }),
  draftStatements: (month: string) =>
    apiRequest<StatementRun>(`${base}/arb/statements`, { method: "POST", json: { month } }),
  sendStatements: (month: string) =>
    apiRequest<StatementRun>(`${base}/arb/statements/send`, { method: "POST", json: { month } }),
  sanctions: () => apiRequest<SanctionsStatus>(`${base}/sanctions`),
  refreshSanctions: () => apiRequest<SanctionsStatus>(`${base}/sanctions/refresh`, { method: "POST" }),
  catalog: () => apiRequest<CapacityInfo[]>(`${base}/capacities/catalog`),
  assignments: () => apiRequest<Assignment[]>(`${base}/capacities`),
  grant: (body: { user_id: string; capacity: FinanceCapacity; entity_id: string | null }) =>
    apiRequest<Assignment>(`${base}/capacities`, { method: "POST", json: body }),
  revoke: (id: string) =>
    apiRequest<void>(`${base}/capacities/${encodeURIComponent(id)}`, { method: "DELETE" }),
}

/** The vendor's public portal: the signed link is the only access (no session). */
export const portalApi = {
  view: (token: string) => apiRequest<PortalView>(`/vendor-portal/${encodeURIComponent(token)}`, { skipAuthRefresh: true }),
  upload: ({ token, kind, file }: { token: string; kind: string; file: File }) => {
    const form = new FormData()
    form.append("file", file)
    form.append("kind", kind)
    return apiRequest<{ kind: string; filename: string; uploaded_at: string }>(
      `/vendor-portal/${encodeURIComponent(token)}/documents`,
      { method: "POST", form, skipAuthRefresh: true },
    )
  },
}

export interface StatementRun {
  drafted: string[]
  sent: string[]
  skipped: string[]
}

export interface ClientApplication {
  legal_name: string
  trading_name?: string | null
  tax_id?: string | null
  country: string
  address: string
  billing_email: string
  established_year?: number | null
  requested_limit: string
  requested_terms_days: number
  trade_references: { company: string; contact_email: string }[]
}

export interface ClientPortalView {
  client_name: string
  expires_at: string
  required: string[]
  uploaded: { kind: string; filename: string; uploaded_at: string }[]
  application: ClientApplication | null
  open: boolean
}

/** A client's public account application: the signed link is the only access (no session). */
export const clientPortalApi = {
  view: (token: string) =>
    apiRequest<ClientPortalView>(`/client-portal/${encodeURIComponent(token)}`, { skipAuthRefresh: true }),
  upload: ({ token, kind, file }: { token: string; kind: string; file: File }) => {
    const form = new FormData()
    form.append("file", file)
    form.append("kind", kind)
    return apiRequest<{ kind: string; filename: string; uploaded_at: string }>(
      `/client-portal/${encodeURIComponent(token)}/documents`,
      { method: "POST", form, skipAuthRefresh: true },
    )
  },
  apply: ({ token, body }: { token: string; body: ClientApplication }) =>
    apiRequest<ClientPortalView>(`/client-portal/${encodeURIComponent(token)}/application`, {
      method: "POST",
      json: body,
      skipAuthRefresh: true,
    }),
}
