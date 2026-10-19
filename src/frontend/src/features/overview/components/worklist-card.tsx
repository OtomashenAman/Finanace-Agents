import { Inbox } from "lucide-react"

import { cn } from "@/lib/utils"

import type { WorklistItem } from "../api"

const STATUS_LABELS: Record<string, string> = {
  requires_review: "Requires Review",
  policy_exception: "Policy Exception",
  reconciliation: "Reconciliation",
  pending_approval: "Pending Approval",
}

function StatusBadge({ status }: { status: string }) {
  const label = STATUS_LABELS[status] ?? status.replace(/_/g, " ")
  const positive = status === "requires_review"
  return (
    <span
      className={cn(
        "inline-flex min-w-36 justify-center rounded px-3 py-1.5 text-xs font-semibold",
        positive ? "bg-emerald-50 text-emerald-800" : "bg-amber-50 text-amber-800",
      )}
    >
      {label}
    </span>
  )
}

export function WorklistCard({ items }: { items: WorklistItem[] }) {
  return (
    <section className="rounded-lg border bg-card p-5 sm:p-6" aria-labelledby="worklist-title">
      <h2 id="worklist-title" className="border-b pb-4 text-lg font-semibold text-brand-navy">
        Operational worklist
      </h2>

      {items.length === 0 ? (
        <div className="flex flex-col items-center gap-2 py-12 text-center">
          <Inbox className="size-7 text-muted-foreground" aria-hidden />
          <p className="font-medium">No runs need attention</p>
          <p className="max-w-sm text-sm text-muted-foreground">
            Runs started from agent workspaces will appear here with their review status.
          </p>
        </div>
      ) : (
        <ul className="divide-y">
          {items.map((item) => (
            <li key={`${item.agent_key}-${item.reference}`} className="grid grid-cols-[1fr_auto] items-center gap-3 py-3.5 sm:grid-cols-[1.2fr_1fr_auto]">
              <span className="font-semibold text-brand-navy">{item.agent_name}</span>
              <span className="hidden text-sm text-muted-foreground sm:inline">{item.reference}</span>
              <StatusBadge status={item.status} />
            </li>
          ))}
        </ul>
      )}
    </section>
  )
}
