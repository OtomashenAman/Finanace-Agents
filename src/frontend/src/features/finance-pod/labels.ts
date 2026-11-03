import { Bot, CircleCheck, Eye, FileCheck, Mail, Upload } from "lucide-react"

import type { CaseStatus, QueueType, StepKind, StepStatus } from "./api"

/** The requirement's colours: blue AI agent, gold person decides, grey system event, white
 *  manual task. */
export const KIND_META: Record<StepKind, { label: string; box: string; chip: string }> = {
  agent: {
    label: "AI agent",
    box: "border-sky-300 bg-sky-50/60 dark:border-sky-800 dark:bg-sky-950/30",
    chip: "bg-sky-600 text-white",
  },
  person: {
    label: "Person decides",
    box: "border-amber-300 bg-amber-50/60 dark:border-amber-800 dark:bg-amber-950/30",
    chip: "bg-amber-500 text-white",
  },
  system: {
    label: "System event",
    box: "border-slate-300 bg-slate-50 dark:border-slate-700 dark:bg-slate-900/40",
    chip: "bg-slate-500 text-white",
  },
  manual: {
    label: "Manual task",
    box: "border-border bg-card",
    chip: "bg-muted text-foreground",
  },
}

export const STEP_STATUS: Record<StepStatus, { label: string; className: string }> = {
  pending: { label: "Pending", className: "bg-muted text-muted-foreground" },
  done: { label: "Done", className: "bg-emerald-50 text-emerald-800 dark:bg-emerald-950/50 dark:text-emerald-300" },
  not_applicable: { label: "Not applicable", className: "bg-slate-100 text-slate-700 dark:bg-slate-800 dark:text-slate-300" },
  failed: { label: "Failed", className: "bg-red-50 text-red-800 dark:bg-red-950/50 dark:text-red-300" },
}

export const CASE_STATUS: Record<CaseStatus, { label: string; className: string }> = {
  draft: { label: "In progress", className: "bg-sky-50 text-sky-800 dark:bg-sky-950/50 dark:text-sky-300" },
  approved: { label: "Approved", className: "bg-emerald-50 text-emerald-800 dark:bg-emerald-950/50 dark:text-emerald-300" },
  completed: { label: "Completed", className: "bg-slate-100 text-slate-700 dark:bg-slate-800 dark:text-slate-300" },
  cancelled: { label: "Cancelled", className: "bg-muted text-muted-foreground" },
}

/** "budget_owner" -> "Budget owner" when the catalog isn't at hand */
export function capacityLabel(capacity: string, catalog?: { key: string; label: string }[]): string {
  return catalog?.find((c) => c.key === capacity)?.label ?? capacity.replace(/_/g, " ").replace(/^\w/, (c) => c.toUpperCase())
}

export function formatMeasure(value: string | null, unit: string): string {
  if (value === null) return "—"
  const n = Number(value)
  const shown = Number.isFinite(n) ? n.toLocaleString(undefined, { maximumFractionDigits: 1 }) : value
  return unit === "%" ? `${shown}%` : unit === "count" ? shown : `${shown} ${unit}`
}

/** What kind of work each queue item is, in the order people act on them. */
export const QUEUE_META: Record<QueueType, { group: string; chip: string; label: string; icon: typeof Bot }> = {
  decide: { group: "Approve or decide", label: "Decide", chip: "bg-amber-100 text-amber-900", icon: CircleCheck },
  review: { group: "Review tasks", label: "Review", chip: "bg-rose-100 text-rose-900", icon: Eye },
  mail: { group: "Mail to send", label: "Send mail", chip: "bg-violet-100 text-violet-900", icon: Mail },
  post: { group: "Post to ERPNext", label: "Post", chip: "bg-emerald-100 text-emerald-900", icon: Upload },
  verify: { group: "Verify in ERPNext", label: "Verify", chip: "bg-teal-100 text-teal-900", icon: FileCheck },
  run: { group: "Run the agent", label: "Run agent", chip: "bg-sky-100 text-sky-900", icon: Bot },
}

export const QUEUE_ORDER: QueueType[] = ["decide", "review", "mail", "post", "verify", "run"]

/** One line per workflow for the dashboard cards (the full description is its tooltip). */
export const WORKFLOW_SHORT: Record<string, string> = {
  ap_purchase_request: "From a request to an issued PO",
  ap_vendor_onboarding: "A new vendor, checked and activated by two people",
  ap_invoice_match: "Each supplier invoice matched to its PO and receipt",
  ap_month_close: "The month's accruals, reconciliation and sign-off",
  ar_client_account: "A new client's account and credit terms",
  ar_billing: "Each lab submission billed, checked and sent",
}

