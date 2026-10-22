import { LoaderCircle } from "lucide-react"

import { formatDateTime } from "@/features/agent-catalog/workspace/format"
import { cn } from "@/lib/utils"

import { useRunTimeline } from "../hooks"

/** Who did what on one run, oldest first, straight from the audit trail. */
export function RunTimeline({ agentKey, runId }: { agentKey: string; runId: string }) {
  const { data: events, isPending, isError } = useRunTimeline(agentKey, runId)

  return (
    <div>
      <h3 className="text-sm font-semibold text-brand-navy">Activity</h3>
      {isPending && <LoaderCircle className="mt-2 size-4 animate-spin text-primary" aria-label="Loading" />}
      {isError && <p className="mt-1 text-sm text-muted-foreground">Couldn't load the activity.</p>}
      {events && (
        <ol className="mt-2 space-y-2.5 border-l pl-4">
          {events.map((e) => (
            <li key={e.id} className="relative text-sm">
              <span
                className={cn(
                  "absolute top-1.5 -left-[21px] size-2 rounded-full",
                  e.outcome === "failure" ? "bg-red-600" : "bg-primary",
                )}
                aria-hidden
              />
              <p className={cn(e.outcome === "failure" && "text-red-800")}>{e.summary}</p>
              <p className="text-xs text-muted-foreground">
                {e.actor?.full_name ?? "—"} · {formatDateTime(e.created_at)}
              </p>
            </li>
          ))}
        </ol>
      )}
    </div>
  )
}
