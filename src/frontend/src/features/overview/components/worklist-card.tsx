import { Link } from "react-router"
import { Inbox } from "lucide-react"

import { StatusBadge } from "@/features/agent-catalog/workspace/components/status-badge"
import { formatDateTime } from "@/features/agent-catalog/workspace/format"
import { cn } from "@/lib/utils"

import type { WorklistItem } from "../api"

export function WorklistCard({ items }: { items: WorklistItem[] }) {
  return (
    <section className="rounded-lg border bg-card p-5 sm:p-6" aria-labelledby="worklist-title">
      <div className="flex items-center justify-between gap-3 border-b pb-4">
        <h2 id="worklist-title" className="text-lg font-semibold text-brand-navy">
          Operational worklist
        </h2>
        <Link to="/worklist" className="text-sm font-medium text-primary hover:underline">
          My Worklist
        </Link>
      </div>

      {items.length === 0 ? (
        <div className="flex flex-col items-center gap-2 py-12 text-center">
          <Inbox className="size-7 text-muted-foreground" aria-hidden />
          <p className="font-medium">No runs need attention</p>
          <p className="max-w-sm text-sm text-muted-foreground">
            Runs started from agent workspaces will appear here with their review status.
          </p>
        </div>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full min-w-[620px] text-sm">
            <thead>
              <tr className="border-b text-left text-xs tracking-wide text-muted-foreground uppercase">
                <th className="py-2 pr-3 font-semibold">Agent</th>
                <th className="py-2 pr-3 font-semibold">Entity</th>
                <th className="py-2 pr-3 font-semibold">Owner</th>
                <th className="py-2 pr-3 font-semibold">Created</th>
                <th className="py-2 pr-3 text-right font-semibold">Exceptions</th>
                <th className="py-2 font-semibold">Status</th>
              </tr>
            </thead>
            <tbody className="divide-y">
              {items.map((item) => (
                <tr key={item.run_id} className="hover:bg-secondary/40">
                  <td className="py-3 pr-3">
                    <Link
                      to={`/catalog/${item.agent_key}/runs/${item.run_id}`}
                      className="font-semibold text-brand-navy hover:underline"
                    >
                      {item.agent_name}
                    </Link>
                    <span className="block text-xs text-muted-foreground">
                      {item.reference}
                      {item.priority === "high" && <span className="ml-2 font-semibold text-red-700">High priority</span>}
                    </span>
                  </td>
                  <td className="py-3 pr-3 font-mono text-xs">{item.entity_code ?? "—"}</td>
                  <td className="py-3 pr-3">{item.owner}</td>
                  <td className="py-3 pr-3 whitespace-nowrap text-muted-foreground">{formatDateTime(item.created_at)}</td>
                  <td className={cn("py-3 pr-3 text-right tabular-nums", item.exceptions > 0 && "font-semibold text-red-800")}>
                    {item.exceptions}
                  </td>
                  <td className="py-3">
                    <StatusBadge status={item.status} label={item.status_label} />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  )
}
