import type { CaseStatus, StepKind, StepStatus } from "./api"

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
