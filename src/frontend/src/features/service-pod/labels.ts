import type {
  ArtifactKind,
  CaseStatus,
  Collection,
  MessageStatus,
  ReviewTaskKind,
  TaskStatus,
  WorkflowKey,
} from "./api"
import type { CasePhase } from "./flows/types"

type Tone = "neutral" | "info" | "good" | "warn" | "bad"

export const TONE_CLASSES: Record<Tone, string> = {
  neutral: "bg-muted text-muted-foreground",
  info: "bg-sky-50 text-sky-800",
  good: "bg-emerald-50 text-emerald-800",
  warn: "bg-amber-50 text-amber-800",
  bad: "bg-red-50 text-red-800",
}

export const WORKFLOW_SHORT: Record<WorkflowKey, string> = {
  ar_collections: "AR Collections",
  bank_recon: "Bank-to-Invoice",
  fpa_trend: "FP&A Trends",
  treasury: "Treasury",
  reporting: "Reporting",
}

/** URL segment of each workflow's workspace: /pod/ar, /pod/bank... */
export const WORKFLOW_SLUG: Record<WorkflowKey, string> = {
  ar_collections: "ar",
  bank_recon: "bank",
  fpa_trend: "fpa",
  treasury: "treasury",
  reporting: "reporting",
}

export function workflowFromSlug(slug: string | undefined): WorkflowKey | undefined {
  return (Object.keys(WORKFLOW_SLUG) as WorkflowKey[]).find((k) => WORKFLOW_SLUG[k] === slug)
}

export const CASE_STATUS: Record<CaseStatus, [string, Tone]> = {
  draft: ["In progress", "neutral"],
  approved: ["Approved", "good"],
  completed: ["Completed", "good"],
  cancelled: ["Cancelled", "neutral"],
}

/** A case's status chip, from where its work stands (workflows with steps) */
export const CASE_PHASE: Record<CasePhase, [string, Tone]> = {
  compose: ["Email to send", "neutral"],
  waiting: ["Waiting for reply", "info"],
  analysis: ["In analysis", "info"],
  review: ["Needs review", "warn"],
  ready: ["Ready to approve", "good"],
  posting: ["QuickBooks posting", "info"],
  approved: ["Approved", "good"],
  completed: ["Completed", "good"],
  cancelled: ["Cancelled", "neutral"],
}

/** How an imported reply was tied to our email */
export const THREAD_EVIDENCE: Record<string, string> = {
  header: "matched to our email",
  manual: "linked by hand",
}

export const MESSAGE_STATUS: Record<MessageStatus, [string, Tone]> = {
  draft: ["Draft", "neutral"],
  sending: ["Sending…", "info"],
  sent: ["Sent", "good"],
  send_failed: ["Send failed", "bad"],
  send_unknown: ["Outcome unknown: reconcile", "warn"],
  received: ["Reply received", "info"],
}

export const TASK_STATUS: Record<TaskStatus, [string, Tone]> = {
  proposed: ["To post in QuickBooks", "info"],
  recorded_unverified: ["Recorded, not verified", "warn"],
  verified: ["Verified", "good"],
  cancelled: ["Cancelled", "neutral"],
}

export const REVIEW_KIND: Record<ReviewTaskKind, string> = {
  unknown_date: "Unknown date",
  dispute: "Dispute",
  missing_document: "Missing document",
  ambiguity: "Ambiguity",
  scope: "Scope / as-of date",
  other: "Other",
}

export const ARTIFACT_KIND: Record<ArtifactKind, string> = {
  timesheet: "Timesheet",
  invoice_copy: "Invoice copy",
  msa: "MSA / contract",
  supporting: "Supporting document",
  other: "Other",
}

export const COLLECTION_LABEL: Record<Collection, string> = {
  customers: "Customers",
  invoices: "Invoices",
  payments: "Payments",
  accounts: "Accounts",
  gl_lines: "GL lines",
  transactions: "Transactions",
  bank_receipts: "Bank receipts",
  contracts: "Contracts",
  planned_outflows: "Planned outflows",
  cash_position: "Cash position",
  balance_sheets: "Balance sheets",
  close_status: "Close status",
}

export function formatDateTime(value: string | null): string {
  return value ? new Date(value).toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" }) : "—"
}

export function shortHash(hash: string): string {
  return `${hash.slice(0, 10)}…`
}
