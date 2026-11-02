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

export type Tone = "neutral" | "info" | "good" | "positive" | "warn" | "bad" | "ai" | "violet"

export const TONE_CLASSES: Record<Tone, string> = {
  neutral: "bg-muted text-muted-foreground",
  info: "bg-sky-50 text-sky-800 dark:bg-sky-950/50 dark:text-sky-300",
  good: "bg-emerald-50 text-emerald-800 dark:bg-emerald-950/50 dark:text-emerald-300",
  positive: "bg-emerald-50 text-emerald-800 dark:bg-emerald-950/50 dark:text-emerald-300",
  warn: "bg-amber-50 text-amber-800 dark:bg-amber-950/50 dark:text-amber-300",
  bad: "bg-red-50 text-red-800 dark:bg-red-950/50 dark:text-red-300",
  ai: "bg-violet-50 text-violet-800 border border-violet-200/80 dark:bg-violet-950/50 dark:text-violet-300 dark:border-violet-800/50",
  violet: "bg-violet-50 text-violet-800 border border-violet-200/80 dark:bg-violet-950/50 dark:text-violet-300 dark:border-violet-800/50",
}

export interface AgentMeta {
  key: WorkflowKey
  name: string
  role: string
  avatar: string
  shortName: string
  toneColor: string
  badgeTone: Tone
  description: string
  focus: string
}

export const AI_AGENTS: Record<WorkflowKey, AgentMeta> = {
  ar_collections: {
    key: "ar_collections",
    name: "AR Collections",
    role: "Collections & Dunning",
    avatar: "🤖",
    shortName: "AR Collections",
    toneColor: "text-blue-600 dark:text-blue-400 bg-blue-50/80 dark:bg-blue-950/40 border-blue-200/70",
    badgeTone: "info",
    description: "Monitors open customer invoices, detects aging delinquency, drafts personalized dunning emails, and tracks payment promises.",
    focus: "AR & Dunning",
  },
  bank_recon: {
    key: "bank_recon",
    name: "Bank-to-Invoice Reconciliation",
    role: "Unapplied Cash & Posting",
    avatar: "⚡",
    shortName: "Bank Recon",
    toneColor: "text-emerald-600 dark:text-emerald-400 bg-emerald-50/80 dark:bg-emerald-950/40 border-emerald-200/70",
    badgeTone: "good",
    description: "Auto-matches unapplied wire receipts to open invoices with confidence scoring, verifies payer names, and coordinates posting.",
    focus: "Reconciliation",
  },
  fpa_trend: {
    key: "fpa_trend",
    name: "FP&A Trends",
    role: "Trend Intelligence & Commentary",
    avatar: "📈",
    shortName: "FP&A Trends",
    toneColor: "text-purple-600 dark:text-purple-400 bg-purple-50/80 dark:bg-purple-950/40 border-purple-200/70",
    badgeTone: "ai",
    description: "Computes financial trends, flags MoM/YoY expense anomalies, generates executive driver commentary, and models operational drivers.",
    focus: "Trends & Drivers",
  },
  reporting: {
    key: "reporting",
    name: "Financial Reporting",
    role: "Monthly Management Packs",
    avatar: "📑",
    shortName: "Reporting",
    toneColor: "text-indigo-600 dark:text-indigo-400 bg-indigo-50/80 dark:bg-indigo-950/40 border-indigo-200/70",
    badgeTone: "info",
    description: "Assembles monthly board management packs, validates trial balance equality checks, drafts narrative footnotes, and coordinates Controller/CFO sign-offs.",
    focus: "Management Packs",
  },
  treasury: {
    key: "treasury",
    name: "Treasury Forecast",
    role: "13-Week Cash Forecast",
    avatar: "🏦",
    shortName: "Treasury",
    toneColor: "text-amber-600 dark:text-amber-400 bg-amber-50/80 dark:bg-amber-950/40 border-amber-200/70",
    badgeTone: "warn",
    description: "Calculates rolling 91-day cash runway from bank-verified balances, evaluates AR collection tranches by probability, and models Optimistic/Stress shifts.",
    focus: "Cash Runway",
  },
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
