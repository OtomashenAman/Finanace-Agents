import { apiRequest } from "@/lib/api"

export type WorkflowKey = "ar_collections" | "bank_recon" | "fpa_trend" | "treasury" | "reporting"
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
  // Procure-to-Pay (Finance POD, from an ERP such as ERPNext)
  | "vendors"
  | "items"
  | "item_prices"
  | "vendor_contracts"
  | "cost_centres"
  | "labs"
  | "grants"
  | "budgets"
  | "budget_actuals"
  | "purchase_requests"
  | "supplier_quotations"
  | "purchase_orders"
  | "purchase_receipts"
  | "bills"
export type CaseStatus = "draft" | "approved" | "completed" | "cancelled"
export type MessageStatus = "draft" | "sending" | "sent" | "send_failed" | "send_unknown" | "received"
export type TaskStatus = "proposed" | "recorded_unverified" | "verified" | "cancelled"
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
  required: Collection[]
  /** The capacity sign-offs are given in, e.g. "Finance Head" (the Finance Admin signs) */
  signoff_as: string
  /** Every sign-off in order, e.g. ["Controller", "CFO"] */
  signoffs: string[]
}

export interface Snapshot {
  id: string
  entity: EntityRef
  parent_id: string | null
  source_type: "json_export" | "bank_csv" | "quickbooks_online" | "qbxml" | "erpnext"
  provenance: "QUICKBOOKS_READONLY_EXPORT" | "SYNTHETIC_DEMO" | "ERP_READONLY_EXPORT"
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
  used_by_cases: number
  /** Why it can't be deleted (cases, a verified posting, a later snapshot); null: unused */
  in_use: string | null
  archived: boolean
  archived_reason: string | null
  archived_by: string | null
  archived_at: string | null
}

export interface SnapshotImportResult {
  snapshot: Snapshot
  created: boolean
  /** What the import couldn't include, and why */
  notes: string[]
}

export interface CaseSummary {
  id: string
  reference: string
  workflow: WorkflowKey
  title: string
  status: CaseStatus
  /** The step an open case is on (workflows with steps), "done" when closed */
  stage: string | null
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
  user: PersonRef
  content_hash: string
  /** e.g. "Finance Head": the sign-off this approval stands for */
  capacity: string
  valid: boolean
  created_at: string
}

export interface ReviewTask {
  id: string
  kind: ReviewTaskKind
  subject: string | null
  detail: string
  blocking: boolean
  /** What settles it when a note isn't enough (a customer's dated reply, a matching document) */
  requirement: { type: "customer_date" | "document"; kind?: string; invoice?: string | null } | null
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
  case_reference: string
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
  /** The source's verified figures, which must stay in the body unchanged */
  fact_block: string | null
  approval_checks: ApprovalChecks | null
  /** Replies: what the AI read, with provenance and notes, or why it couldn't */
  extraction: { output?: Record<string, unknown>; provenance?: Record<string, string>; notes?: string[]; error?: string } | null
  /** case_closed: came after the case closed, kept but not read into it */
  extraction_status: "pending" | "done" | "failed" | "skipped" | "case_closed" | null
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
  /** null: read from the mailbox by the worker */
  created_by: string | null
  created_at: string
  updated_at: string
}

export interface ApprovalChecks {
  recipient: boolean
  mapping: boolean
  tone: boolean
}

export interface Composed {
  to_email: string | null
  to_name: string | null
  subject: string
  body: string
  fact_block: string | null
  ai_drafted: boolean
  note: string | null
}

export interface InvoiceRow {
  id: string
  number: string
  due_date: string
  balance: string
  days_overdue: number
}

export interface CaseRef {
  id: string
  reference: string
  status: CaseStatus
}

export interface ArPortfolio {
  snapshot: Snapshot | null
  currency: string | null
  ar_balance: string
  overdue_over_30: string
  approved_promises: string
  open_exceptions: number
  aging: { label: string; amount: string; count: number }[]
  customers: {
    customer_id: string
    name: string
    email: string | null
    overdue: string
    max_days_overdue: number
    invoices: InvoiceRow[]
    open_case: CaseRef | null
    next_action: string
  }[]
  /** Approved promises being watched, overdue first */
  promises: PromiseRow[]
}

export interface PromiseRow {
  case_id: string
  case_reference: string
  customer: string
  invoice_number: string
  amount: string
  expected_date: string
  /** negative: overdue by that many days */
  days_until: number
  state: "upcoming" | "due" | "overdue" | "received"
  /** the evidence of cash: a verified bank posting or a newer source */
  received_by: string | null
}

export interface RelatedCase {
  id: string
  reference: string
  workflow: WorkflowKey
  title: string
  status: CaseStatus
  summary: string | null
}

export interface BankWorklist {
  snapshot: Snapshot | null
  unmatched_total: string
  receipts: number
  possible_duplicates: number
  pending_admin: number
  rows: {
    reference: string
    payer: string
    date: string
    amount: string
    currency: string
    cleared: boolean
    matched_customer_id: string | null
    matched_customer: string | null
    open_invoices: InvoiceRow[]
    possible_duplicate: boolean
    open_case: CaseRef | null
  }[]
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

export type TaskActionName = "record" | "verify" | "cancel"

export interface PostingTask {
  id: string
  case_id: string
  case_reference: string
  workflow: WorkflowKey
  kind: "receive_payment" | "journal_entry" | "create_supplier" | "create_purchase_order"
  reference: string
  status: TaskStatus
  version: number
  instructions: Record<string, unknown>
  note: string | null
  proposed_by: string
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
  | "approve"
  | "complete"
  | "cancel"
  | "add_review_task"
  | "resolve_review_task"
  | "add_action"
  | "update_action"
  | "propose_commitment"
  | "decide_commitment"
  | "refresh_source"
  | "set_allocation"
  | "create_posting_task"
  | "set_commentary"
  | "confirm_mapping"
  | "propose_correction"
  | "withdraw_correction"
  | "queue_correction"
  | "review_receipt"
  | "add_shift"
  | "remove_shift"

export interface CaseDetail extends CaseSummary {
  snapshot: Snapshot
  selection: Record<string, unknown>
  state: Record<string, unknown>
  completed_at: string | null
  fingerprint: string
  approvals: Approval[]
  review_tasks: ReviewTask[]
  owned_actions: OwnedAction[]
  commitments: Commitment[]
  messages: Message[]
  artifacts: Artifact[]
  posting_tasks: PostingTask[]
  /** Other workflows' cases about the same customer (e.g. the bank receipt paying a promise) */
  related_cases: RelatedCase[]
  blockers: string[]
  completion_blockers: string[]
  /** The sign-off the case waits for (e.g. "CFO"); null: none now */
  next_signoff: string | null
  /** null: it can be done now; otherwise why not */
  allowed_actions: Record<CaseActionName, string | null>
}

export type DashboardPhase = "compose" | "waiting" | "analysis" | "review" | "ready" | "approved" | "closed"

export interface PromiseItem {
  case_id: string
  case_reference: string
  case_title: string
  invoice_number: string
  amount: string
  currency: string
  expected_date: string
}

export type AiKind = "reply_read" | "reply_not_read" | "commentary" | "reply_imported"

export interface Dashboard {
  ai_activity: {
    last_7_days: Record<AiKind, number>
    recent: { at: string; kind: AiKind; summary: string; case_reference: string | null }[]
  }
  cash: {
    case_id: string
    case_reference: string
    currency: string
    opening: string
    buffer: string
    ending_cash: string
    first_breach: string | null
    weeks: { to: string; ending_cash: string }[]
  } | null
  open_cases: number
  closed_30d: number
  phases: Record<DashboardPhase, number>
  promised: { currency: string; amount: string }[]
  due_this_week: PromiseItem[]
  overdue_promises: PromiseItem[]
  aging: { label: string; count: number }[]
  open: { id: string; reference: string; title: string; workflow: WorkflowKey; phase: DashboardPhase; days_open: number }[]
  email: {
    provider: string
    simulated: boolean
    ready: boolean
    problem: string | null
    reads_mailbox: boolean
    poll_seconds: number | null
    last_reply_at: string | null
    sent_30d: number
    replies_30d: number
    avg_reply_hours: number | null
  }
}

export interface FpaPeriodSource {
  snapshot: Snapshot
  months: string[]
  business_units: string[]
  suggested_start: string | null
  suggested_end: string | null
}

export interface FpaPeriods {
  sources: FpaPeriodSource[]
  cases: { id: string; reference: string; title: string; status: CaseStatus; start: string; end: string }[]
}

export interface FpaDrill {
  account: { id: string; name: string; number: string | null; classification: string }
  period: string
  gl_lines: { id: string; amount: string; report_id: string; transaction_ids: string[] }[]
  transactions: {
    id: string
    date: string
    type: string
    counterparty: string | null
    amount: string
    status: string
    document_ref: string | null
    gl_line_id: string | null
  }[]
}

export interface ReportMonths {
  sources: {
    snapshot: Snapshot
    months: { month: string; closed: boolean; balance_sheet: boolean; prior_available: boolean }[]
    business_units: string[]
    suggested: string | null
  }[]
  cases: { id: string; reference: string; title: string; status: CaseStatus; month: string }[]
  internal_recipients: string[]
}

export interface ReportPack {
  id: string
  number: number
  sha256: string
  size: number
  content_hash: string
  source_sha: string
  reviewers: { capacity: string; name: string; at: string }[]
  artifact_id: string
  current: boolean
  created_at: string
}

export interface TreasurySources {
  sources: {
    snapshot: Snapshot
    opening_cash: string | null
    policy_buffer: string | null
    checks: string[]
    approved_outflows: string
    commitments: number
  }[]
  cases: { id: string; reference: string; title: string; status: CaseStatus; as_of: string }[]
}

export interface PurgePreview {
  snapshots: { id: string; company_name: string; as_of: string; source_type: string; is_demo: boolean }[]
  cases: { id: string; reference: string; title: string; workflow: string; status: CaseStatus }[]
  messages: number
  documents: number
  posting_tasks: number
  review_tasks: number
  commitments: number
  approvals: number
  verified_elsewhere: number
  /** Real books with approved / completed work or verified postings */
  evidence: boolean
  all_demo: boolean
}

export interface UserDataPreview extends PurgePreview {
  user_name: string
  data_sources: string[]
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
  /** Test mode: every email goes to this address instead of the customer */
  test_recipient: string | null
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
  dashboard: () => apiRequest<Dashboard>("/pod/dashboard"),
  fpaPeriods: () => apiRequest<FpaPeriods>("/pod/fpa/periods"),
  reportMonths: () => apiRequest<ReportMonths>("/pod/reporting/months"),
  treasurySources: () => apiRequest<TreasurySources>("/pod/treasury/sources"),
  snapshotDependents: (id: string) => apiRequest<PurgePreview>(`/pod/snapshots/${id}/dependents`),
  purgeSnapshot: ({ id, reason, confirm }: { id: string; reason: string; confirm: string }) =>
    apiRequest<PurgePreview>(`/pod/snapshots/${id}/purge`, { method: "POST", json: { reason, confirm } }),
  sourceDependents: (sourceId: string) => apiRequest<PurgePreview>(`/pod/snapshots/sources/${sourceId}/dependents`),
  userData: (userId: string) => apiRequest<UserDataPreview>(`/pod/snapshots/users/${userId}/data`),
  removeUserData: ({ userId, reason, confirm }: { userId: string; reason: string; confirm: string }) =>
    apiRequest<UserDataPreview>(`/pod/snapshots/users/${userId}/data/remove`, { method: "POST", json: { reason, confirm } }),
  reportPacks: (caseId: string) => apiRequest<ReportPack[]>(`/pod/reporting/cases/${caseId}/packs`),
  exportPack: (caseId: string) => apiRequest<ReportPack>(`/pod/reporting/cases/${caseId}/packs`, { method: "POST" }),
  fpaCommentary: ({ caseId, version }: { caseId: string; version: number }) =>
    apiRequest<CaseDetail>(`/pod/fpa/cases/${caseId}/commentary`, { method: "POST", json: { expected_version: version } }),
  fpaDrill: ({ caseId, accountId, period }: { caseId: string; accountId: string; period: string }) =>
    apiRequest<FpaDrill>(`/pod/fpa/cases/${caseId}/drill${qs({ account_id: accountId, period })}`),

  snapshots: (includeArchived = false) =>
    apiRequest<Snapshot[]>(`/pod/snapshots${includeArchived ? "?include_archived=true" : ""}`),
  archiveSnapshot: ({ id, reason }: { id: string; reason: string }) =>
    apiRequest<Snapshot>(`/pod/snapshots/${id}/archive`, { method: "POST", json: { reason } }),
  restoreSnapshot: (id: string) => apiRequest<Snapshot>(`/pod/snapshots/${id}/restore`, { method: "POST" }),
  deleteSnapshot: ({ id, reason }: { id: string; reason: string }) =>
    apiRequest<void>(`/pod/snapshots/${id}`, { method: "DELETE", json: { reason } }),
  snapshotRows: (id: string, collection: Collection) =>
    apiRequest<{ collection: Collection; rows: Record<string, unknown>[] }>(
      `/pod/snapshots/${id}/rows${qs({ collection })}`,
    ),
  importJson: ({ file, entityId }: { file: File; entityId: string }) => {
    const form = new FormData()
    form.append("file", file)
    form.append("entity_id", entityId)
    // The same normalized export as JSON or as an Excel workbook (sheet per collection)
    const kind = file.name.toLowerCase().endsWith(".xlsx") ? "workbook" : "json"
    return apiRequest<SnapshotImportResult>(`/pod/snapshots/${kind}`, { method: "POST", form })
  },
  importQuickBooks: (body: { data_source_id: string; entity_id: string; currency: string; basis: string }) =>
    apiRequest<SnapshotImportResult>("/pod/snapshots/quickbooks", { method: "POST", json: body }),
  /** Freeze a connected ERPNext company's purchasing data (Finance POD) */
  importErpNext: (body: { data_source_id: string; entity_id: string }) =>
    apiRequest<SnapshotImportResult>("/pod/snapshots/erpnext", { method: "POST", json: body }),
  importQbxml: ({
    file,
    entityId,
    currency,
    basis,
    asOf,
  }: {
    file: File
    entityId: string
    currency: string
    basis: string
    asOf: string
  }) => {
    const form = new FormData()
    form.append("file", file)
    form.append("entity_id", entityId)
    form.append("currency", currency)
    form.append("basis", basis)
    form.append("as_of", asOf)
    return apiRequest<SnapshotImportResult>("/pod/snapshots/qbxml", { method: "POST", form })
  },
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
  /** Approves the exact message (customer mail needs the checks) and sends it once */
  sendMessage: ({ id, version, checks }: { id: string; version: number; checks: ApprovalChecks }) =>
    apiRequest<Message>(`/pod/messages/${id}/send`, { method: "POST", json: { expected_version: version, checks } }),
  compose: ({ caseId, purpose }: { caseId: string; purpose: string }) =>
    apiRequest<Composed>(`/pod/cases/${caseId}/messages/compose`, { method: "POST", json: { purpose } }),
  arPortfolio: () => apiRequest<ArPortfolio>("/pod/ar/portfolio"),
  bankWorklist: () => apiRequest<BankWorklist>("/pod/bank/unapplied"),
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
}
