import { cn } from "@/lib/utils"

import type { RunStatus } from "../api"

const TONE: Record<RunStatus, string> = {
  draft: "bg-slate-100 text-slate-700",
  validation_failed: "bg-red-50 text-red-800",
  analyzed: "bg-amber-50 text-amber-800",
  pending_approval: "bg-blue-50 text-blue-800",
  changes_requested: "bg-amber-50 text-amber-800",
  approved: "bg-emerald-50 text-emerald-800",
  rejected: "bg-red-50 text-red-800",
}

export function StatusBadge({ status, label, className }: { status: RunStatus; label: string; className?: string }) {
  return (
    <span
      className={cn(
        "inline-flex items-center justify-center rounded px-2.5 py-1 text-xs font-semibold whitespace-nowrap",
        TONE[status],
        className,
      )}
    >
      {label}
    </span>
  )
}
