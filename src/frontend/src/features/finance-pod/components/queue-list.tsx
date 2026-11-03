import { Link } from "react-router"

import { cn } from "@/lib/utils"

import type { QueueItem } from "../api"
import { QUEUE_META } from "../labels"

function waited(since: string): string {
  const days = Math.floor((Date.now() - new Date(since).getTime()) / 86_400_000)
  return days <= 0 ? "today" : days === 1 ? "1 day" : `${days} days`
}

/** One piece of work: what to do (in words), on which case, and for how long it has waited. */
export function QueueRow({ item }: { item: QueueItem }) {
  const meta = QUEUE_META[item.type]
  const Icon = meta.icon
  return (
    <li>
      <Link
        to={`/finance/cases/${item.case_id}`}
        className="flex items-center gap-3 rounded-md px-2 py-2.5 transition-colors hover:bg-muted/60"
      >
        <span className={cn("flex w-24 shrink-0 items-center justify-center gap-1 rounded-full px-2 py-0.5 text-xs font-medium", meta.chip)}>
          <Icon className="size-3.5" aria-hidden /> {meta.label}
        </span>
        <span className="min-w-0 flex-1">
          <span className="block truncate text-sm font-medium">{item.step_title}</span>
          <span className="block truncate text-xs text-muted-foreground">
            <span className="font-medium text-primary">{item.reference}</span> · {item.case_title}
            {item.kind && item.step_key && <span className="ml-1 font-mono">({item.step_key})</span>}
          </span>
        </span>
        <span className="shrink-0 text-xs text-muted-foreground">{waited(item.waiting_since)}</span>
      </Link>
    </li>
  )
}
