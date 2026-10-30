import { apiRequest } from "@/lib/api"

export type WorkflowKey = "ar_collections" | "bank_recon" | "fpa_trend" | "treasury" | "reporting"
export type Capacity = "preparer" | "reviewer" | "final_approver" | "poster"
export type Collection =
  | "customers"
  | "invoices"
  | "payments"
  | "accounts"
  | "gl_lines"
  | "transactions"
  | "bank_receipts"
  | "contracts"
  | "planned_outflows"
  | "cash_position"
  | "balance_sheets"
  | "close_status"
export type CaseStatus =
  | "draft"
  | "in_review"
  | "awaiting_final"
  | "approved"
  | "changes_requested"
  | "rejected"
  | "completed"
  | "cancelled"
export type MessageStatus = "draft" | "approved" | "sending" | "sent" | "send_failed" | "send_unknown" | "received"
export type TaskStatus = "proposed" | "approved" | "recorded_unverified" | "verified" | "cancelled"
export type ReviewTaskKind = "unknown_date" | "dispute" | "missing_document" | "ambiguity" | "scope" | "other"
export type ArtifactKind = "timesheet" | "invoice_copy" | "msa" | "supporting" | "other"

export interface EntityRef {
  id: string
  code: string
  name: string
}

export interface PersonRef {
  id: string
  name: string
}

export interface Workflow {
  key: WorkflowKey
  name: string
  prefix: string
  description: string
  labels: Partial<Record<Capacity, string>>
  required: Collection[]
  final_gate: boolean
  my_capacities: Capacity[]
}

export interface Snapshot {
  id: string
  entity: EntityRef
  parent_id: string | null
  source_type: "json_export" | "bank_csv" | "quickbooks_online"
  provenance: "QUICKBOOKS_READONLY_EXPORT" | "SYNTHETIC_DEMO"
  is_demo: boolean
  company_id: string
  company_name: string
  currency: string
  basis: "Accrual" | "Cash"
  as_of: string
  source_reference: string
  sha256: string
  coverage: Collection[]
  row_counts: Partial<Record<Collection, number>>
  imported_by: string
  imported_at: string
}

export interface SnapshotImportResult {
  snapshot: Snapshot
  created: boolean
}

export interface CaseSummary {
  id: string
  reference: string
  workflow: WorkflowKey
  title: string
  status: CaseStatus
  stage: string
  version: number
  entity: EntityRef
  owner: PersonRef
  snapshot_id: string
  is_demo: boolean
  open_review_tasks: number
  created_at: string
  updated_at: string
}

export interface Approval {
  id: string
  gate: "review" | "final"
  decision: "approved" | "changes_requested" | "rejected"
  user: PersonRef
  comment: string | null
  content_hash: string
  policy_version: string | null
  valid: boolean
  created_at: string
}

export interface ReviewTask {
  id: string
  kind: ReviewTaskKind
  subject: string | null
  detail: string
  blocking: boolean
  status: "open" | "resolved"
  resolution: string | null
  created_by: string | null
  resolved_by: string | null
  resolved_at: string | null
  created_at: string
}

export interface OwnedAction {
  id: string
  title: string
  owner: PersonRef
  due_date: string
  status: "open" | "done" | "cancelled"
  outcome: string | null
  created_at: string
  updated_at: string
}

export interface Commitment {
  id: string
  invoice_id: string
  invoice_number: string
  amount: string
  expected_date: string | null
  probability: string
  probability_rationale: string | null
  quote: string | null
  source_message_id: string | null
  status: "proposed" | "approved" | "rejected"
  created_by: string | null
  decided_by: string | null
  decided_at: string | null
  created_at: string
}

export interface Message {
  id: string
  case_id: string
  direction: "outbound" | "inbound"
  audience: "customer" | "internal" | null
  purpose: string
  status: MessageStatus
  version: number
  to_email: string
  to_name: string | null
  from_email: string | null
  subject: string
  body: string
  artifact_ids: string[]
  approved_by: string | null
  approved_at: string | null
  provider: string | null
  sender: string | null
  simulated: boolean
  provider_message_id: string | null
  sent_at: string | null
  error: string | null
  internet_message_id: string | null
  in_reply_to_id: string | null
  thread_evidence: "header" | "manual" | null
  received_at: string | null
  created_by: string
  created_at: string
  updated_at: string
}

export interface Artifact {
  id: string
  case_id: string
  kind: ArtifactKind
  invoice_refs: string[]
  filename: string
  content_type: string
  size: number
  sha256: string
  status: "pending" | "approved" | "rejected"
  uploaded_by: string
  decided_by: string | null
  decided_at: string | null
  created_at: string
}

export type TaskActionName = "approve" | "record" | "verify" | "cancel"

export interface PostingTask {
  id: string
  case_id: string
  case_reference: string
  workflow: WorkflowKey
  kind: "receive_payment" | "journal_entry"
  reference: string
  status: TaskStatus
  version: number
  instructions: Record<string, unknown>
  note: string | null
  proposed_by: string
  approved_by: string | null
  approved_at: string | null
  external_txn_id: string | null
  recorded_by: string | null
  recorded_at: string | null
  verified_by: string | null
  verified_at: string | null
  verification_snapshot_id: string | null
  verification: Record<string, unknown> | null
  created_at: string
  allowed_actions: Record<TaskActionName, string | null>
}

export type CaseActionName =
  | "edit"
  | "submit"
  | "review"
  | "final_review"
  | "complete"
  | "cancel"
  | "add_review_task"
  | "resolve_review_task"
  | "add_action"
  | "update_action"
  | "propose_commitment"
  | "decide_commitment"

export interface CaseDetail extends CaseSummary {
  snapshot: Snapshot
  selection: Record<string, unknown>
  state: Record<string, unknown>
  completed_at: string | null
  fingerprint: string
  my_roles: ("owner" | "reviewer" | "final_approver")[]
  approvals: Approval[]
  review_tasks: ReviewTask[]
  owned_actions: OwnedAction[]
  commitments: Commitment[]
  messages: Message[]
  artifacts: Artifact[]
  posting_tasks: PostingTask[]
  blockers: string[]
  completion_blockers: string[]
  /** null: the viewer may do it now; otherwise why not */
  allowed_actions: Record<CaseActionName, string | null>
}

export interface ReviewQueueItem {
  task: ReviewTask
  case_id: string
  case_reference: string
  workflow: WorkflowKey
  case_title: string
}

export interface EmailStatus {
  provider: string
  simulated: boolean
  sender: string | null
  ready: boolean
  problem: string | null
  internal_recipients: string[]
}

export interface PodUserAccess {
  user_id: string
  email: string
  full_name: string
  role: "finance_admin" | "user"
  assignments: { workflow: WorkflowKey; capacity: Capacity }[]
}

export interface MessageDraft {
  audience: "customer" | "internal"
  purpose: string
  to_email: string
  to_name?: string | null
  subject: string
  body: string
  artifact_ids: string[]
}

const qs = (params: Record<string, string | null | undefined>) => {
  const search = new URLSearchParams()
  for (const [k, v] of Object.entries(params)) if (v) search.set(k, v)
  const s = search.toString()
  return s ? `?${s}` : ""
}

export const podApi = {
  workflows: () => apiRequest<Workflow[]>("/pod/workflows"),
  emailStatus: () => apiRequest<EmailStatus>("/pod/email-status"),

  snapshots: () => apiRequest<Snapshot[]>("/pod/snapshots"),
  snapshotRows: (id: string, collection: Collection) =>
    apiRequest<{ collection: Collection; rows: Record<string, unknown>[] }>(
      `/pod/snapshots/${id}/rows${qs({ collection })}`,
    ),
  importJson: ({ file, entityId }: { file: File; entityId: string }) => {
    const form = new FormData()
    form.append("file", file)
    form.append("entity_id", entityId)
    return apiRequest<SnapshotImportResult>("/pod/snapshots/json", { method: "POST", form })
  },
  importQuickBooks: (body: { data_source_id: string; entity_id: string; currency: string; basis: string }) =>
    apiRequest<SnapshotImportResult>("/pod/snapshots/quickbooks", { method: "POST", json: body }),
  importBankStatement: ({ snapshotId, file }: { snapshotId: string; file: File }) => {
    const form = new FormData()
    form.append("file", file)
    return apiRequest<SnapshotImportResult>(`/pod/snapshots/${snapshotId}/bank-statement`, { method: "POST", form })
  },

  cases: (filters: { workflow?: string | null; status?: string | null }) =>
    apiRequest<CaseSummary[]>(`/pod/cases${qs(filters)}`),
  case: (id: string) => apiRequest<CaseDetail>(`/pod/cases/${id}`),
  createCase: (body: { workflow: WorkflowKey; snapshot_id: string; title: string; selection?: Record<string, unknown> }) =>
    apiRequest<CaseDetail>("/pod/cases", { method: "POST", json: body }),
  caseAction: ({
    id,
    action,
    version,
    payload = {},
  }: {
    id: string
    action: CaseActionName
    version: number
    payload?: Record<string, unknown>
  }) =>
    apiRequest<CaseDetail>(`/pod/cases/${id}/actions`, {
      method: "POST",
      json: { action, expected_version: version, payload },
    }),
  reviewQueue: () => apiRequest<ReviewQueueItem[]>("/pod/review-queue"),

  messages: (status?: MessageStatus | null) => apiRequest<Message[]>(`/pod/messages${qs({ status })}`),
  createDraft: ({ caseId, draft }: { caseId: string; draft: MessageDraft }) =>
    apiRequest<Message>(`/pod/cases/${caseId}/messages`, { method: "POST", json: draft }),
  updateMessage: ({ id, version, ...changes }: { id: string; version: number } & Partial<MessageDraft>) =>
    apiRequest<Message>(`/pod/messages/${id}`, { method: "PATCH", json: { expected_version: version, ...changes } }),
  messageStep: ({ id, version, step }: { id: string; version: number; step: "approve" | "send" }) =>
    apiRequest<Message>(`/pod/messages/${id}/${step}`, { method: "POST", json: { expected_version: version } }),
  reconcile: ({
    id,
    version,
    outcome,
    note,
    provider_message_id,
  }: {
    id: string
    version: number
    outcome: "sent" | "send_failed"
    note: string
    provider_message_id?: string
  }) =>
    apiRequest<Message>(`/pod/messages/${id}/reconcile`, {
      method: "POST",
      json: { expected_version: version, outcome, note, provider_message_id },
    }),
  importReply: ({
    caseId,
    ...body
  }: {
    caseId: string
    raw_eml?: string
    from_email?: string
    subject?: string
    body?: string
    reply_to_message_id?: string
  }) => apiRequest<Message>(`/pod/cases/${caseId}/replies`, { method: "POST", json: body }),

  uploadArtifact: ({
    caseId,
    file,
    kind,
    invoiceRefs,
  }: {
    caseId: string
    file: File
    kind: ArtifactKind
    invoiceRefs: string
  }) => {
    const form = new FormData()
    form.append("file", file)
    form.append("kind", kind)
    form.append("invoice_refs", invoiceRefs)
    return apiRequest<Artifact>(`/pod/cases/${caseId}/artifacts`, { method: "POST", form })
  },
  decideArtifact: ({ id, decision }: { id: string; decision: "approved" | "rejected" }) =>
    apiRequest<Artifact>(`/pod/artifacts/${id}/decision`, { method: "POST", json: { decision } }),

  tasks: (status?: TaskStatus | null) => apiRequest<PostingTask[]>(`/pod/tasks${qs({ status })}`),
  proposeTask: ({
    caseId,
    ...body
  }: {
    caseId: string
    kind: PostingTask["kind"]
    reference: string
    instructions: Record<string, unknown>
    note?: string
  }) => apiRequest<PostingTask>(`/pod/cases/${caseId}/tasks`, { method: "POST", json: body }),
  taskAction: ({
    id,
    version,
    action,
    ...extra
  }: {
    id: string
    version: number
    action: TaskActionName
    external_txn_id?: string
    snapshot_id?: string
    note?: string
  }) =>
    apiRequest<PostingTask>(`/pod/tasks/${id}/actions`, {
      method: "POST",
      json: { action, expected_version: version, ...extra },
    }),

  assignments: () => apiRequest<PodUserAccess[]>("/pod/assignments"),
  setAssignments: ({ userId, assignments }: { userId: string; assignments: PodUserAccess["assignments"] }) =>
    apiRequest<PodUserAccess>(`/pod/assignments/${userId}`, { method: "PUT", json: { assignments } }),
}
