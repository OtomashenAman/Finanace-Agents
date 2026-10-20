import type { EntityRef } from "@/features/entities/api"
import { apiRequest } from "@/lib/api"

export type RunStatus =
  | "draft"
  | "validation_failed"
  | "analyzed"
  | "pending_approval"
  | "changes_requested"
  | "approved"
  | "rejected"

export type FieldKind = "text" | "textarea" | "money" | "number" | "percent" | "boolean"
export type FieldValue = string | number | boolean | null
export type ReviewDecision = "approved" | "rejected" | "changes_requested"
export type FlagSeverity = "pass" | "info" | "warning" | "high"

export interface FormField {
  name: string
  label: string
  kind: FieldKind
  required: boolean
  help: string | null
  max_length: number | null
}

export interface FormSpec {
  agent_key: string
  fields: FormField[]
  controls: string[]
}

export interface Person {
  id: string
  full_name: string
}

export interface RunSummary {
  id: string
  reference: string
  agent_key: string
  agent_name: string
  business_reference: string | null
  /** null for runs from before legal entities were set up */
  entity: EntityRef | null
  status: RunStatus
  status_label: string
  priority: "normal" | "high"
  headline: string | null
  preparer: Person
  created_at: string
  updated_at: string
}

export interface Flag {
  code: string
  severity: FlagSeverity
  message: string
  field: string | null
}

export interface Calculation {
  key: string
  label: string
  value: string | null
  kind: "money" | "percent" | "number" | "text"
}

export interface RunDocument {
  id: string
  filename: string
  content_type: string
  size_bytes: number
  sha256: string
  extractor: string
  page_count: number | null
  char_count: number
  truncated: boolean
  warnings: string[]
  text_preview: string
  created_at: string
}

export interface NarrativeOutput {
  summary: string
  key_points: string[]
  cited_fields: string[]
  cited_documents: string[]
  missing_evidence: string[]
  ambiguities: string[]
}

export interface Narrative {
  status: "ok" | "failed" | "not_configured"
  provider: string
  model: string
  prompt_version: string
  output: NarrativeOutput | null
  guard_warnings: string[]
  error: string | null
  input_tokens: number | null
  output_tokens: number | null
  latency_ms: number | null
  created_at: string
}

export interface Review {
  id: string
  reviewer: Person
  decision: ReviewDecision
  comment: string
  result_hash: string
  created_at: string
}

/** Frozen copy of the data source records a run was prefilled from */
export interface RunSource {
  source_id: string | null
  source_kind: "quickbooks" | "upload"
  source_name: string
  record_type: string
  record_reference: string
  records: Record<string, Record<string, unknown>>
  source_synced_at: string | null
  captured_at: string
}

/** Routing fixed on submit by the approval matrix, and progress in this round */
export interface RunApproval {
  required: number
  received: number
  approvers: Person[] // empty = any Finance Admin
  amount: string | null
  tier_min_amount: string | null
  approved_by: Person[]
}

export interface RunDetail extends RunSummary {
  input: Record<string, FieldValue>
  validation_errors: { field: string | null; message: string }[] | null
  proposed_decision: string | null
  policy_version: string | null
  policy_values: Record<string, string | null> | null
  approval: RunApproval | null
  calculations: Calculation[]
  flags: Flag[]
  controls: string[]
  reviewer_label: string
  documents: RunDocument[]
  narrative: Narrative | null
  reviews: Review[]
  source: RunSource | null
  result_hash: string | null
  analyzed_at: string | null
  submitted_at: string | null
  decided_at: string | null
  permissions: {
    can_edit: boolean
    can_analyze: boolean
    can_submit: boolean
    can_review: boolean
    can_delete: boolean
    /** Why the viewer can't decide on a pending run (own run, already approved, not an approver) */
    review_blocked_reason: string | null
  }
}

const base = (key: string) => `/agents/${encodeURIComponent(key)}`
const run = (key: string, id: string) => `${base(key)}/runs/${encodeURIComponent(id)}`

export const runsApi = {
  form: (key: string) => apiRequest<FormSpec>(`${base(key)}/form`),
  list: (key: string, entityId?: string | null) =>
    apiRequest<RunSummary[]>(`${base(key)}/runs${entityId ? `?entity_id=${encodeURIComponent(entityId)}` : ""}`),
  get: (key: string, id: string) => apiRequest<RunDetail>(run(key, id)),
  /** entityId may be omitted when the user works for exactly one legal entity */
  create: (key: string, entityId?: string | null) =>
    apiRequest<RunDetail>(`${base(key)}/runs`, { method: "POST", json: { entity_id: entityId ?? null } }),
  saveInput: (key: string, id: string, values: Record<string, FieldValue>) =>
    apiRequest<RunDetail>(`${run(key, id)}/input`, { method: "PUT", json: { values } }),
  remove: (key: string, id: string) => apiRequest<void>(run(key, id), { method: "DELETE" }),
  analyze: (key: string, id: string) => apiRequest<RunDetail>(`${run(key, id)}/analyze`, { method: "POST" }),
  submit: (key: string, id: string) => apiRequest<RunDetail>(`${run(key, id)}/submit`, { method: "POST" }),
  review: (key: string, id: string, decision: ReviewDecision, comment: string) =>
    apiRequest<RunDetail>(`${run(key, id)}/reviews`, { method: "POST", json: { decision, comment } }),
  uploadDocument: (key: string, id: string, file: File) => {
    const form = new FormData()
    form.append("file", file)
    return apiRequest<RunDetail>(`${run(key, id)}/documents`, { method: "POST", form })
  },
  removeDocument: (key: string, id: string, documentId: string) =>
    apiRequest<RunDetail>(`${run(key, id)}/documents/${encodeURIComponent(documentId)}`, { method: "DELETE" }),
  linkSource: (key: string, id: string, sourceId: string, recordId: string) =>
    apiRequest<RunDetail>(`${run(key, id)}/source`, {
      method: "PUT",
      json: { source_id: sourceId, record_id: recordId },
    }),
  unlinkSource: (key: string, id: string) => apiRequest<RunDetail>(`${run(key, id)}/source`, { method: "DELETE" }),
  documentText: (key: string, id: string, documentId: string) =>
    apiRequest<{ id: string; filename: string; extracted_text: string }>(
      `${run(key, id)}/documents/${encodeURIComponent(documentId)}`,
    ),
}
