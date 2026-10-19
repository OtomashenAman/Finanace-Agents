import { Link } from "react-router"
import { Inbox } from "lucide-react"

import { StatusBadge } from "@/features/agent-catalog/workspace/components/status-badge"

import type { WorklistItem } from "../api"

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
            <li key={item.run_id}>
              <Link
                to={`/catalog/${item.agent_key}/runs/${item.run_id}`}
                className="grid grid-cols-[1fr_auto] items-center gap-3 rounded-md py-3.5 hover:bg-secondary/40 sm:grid-cols-[1.2fr_1fr_auto]"
              >
                <span className="font-semibold text-brand-navy">
                  {item.agent_name}
                  {item.priority === "high" && (
                    <span className="ml-2 align-middle text-xs font-semibold text-red-700">High priority</span>
                  )}
                </span>
                <span className="hidden text-sm text-muted-foreground sm:inline">{item.reference}</span>
                <StatusBadge status={item.status} label={item.status_label} className="min-w-36" />
              </Link>
            </li>
          ))}
        </ul>
      )}
    </section>
  )
}
