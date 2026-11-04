import { Link, useSearchParams } from "react-router"
import { Plus } from "lucide-react"

import { Button } from "@/components/ui/button"
import { Card, Empty, LoadError, Loading, Pill } from "@/features/service-pod/components/bits"
import { selectClass } from "@/features/service-pod/ui"

import type { RequestStatus } from "./api"
import { FpodPage } from "./components/fpod-page"
import { useRequests } from "./hooks"
import { formatDate, money, REQUEST_STATUS } from "./labels"

export function RequestsPage() {
  const [params, setParams] = useSearchParams()
  const status = (params.get("status") as RequestStatus | null) || null
  const mine = params.get("mine") === "true"
  const requests = useRequests({ status, mine })

  const set = (key: string, value: string | null) => {
    const next = new URLSearchParams(params)
    if (value) next.set(key, value)
    else next.delete(key)
    setParams(next, { replace: true })
  }

  return (
    <FpodPage title="Purchase requests" subtitle="Every request, newest first. Open one to see what the request agent found.">
      <Card
        title="Requests"
        actions={
          <div className="flex flex-wrap items-center gap-2">
            <select
              aria-label="Status"
              className={`${selectClass} h-9 w-auto`}
              value={status ?? ""}
              onChange={(e) => set("status", e.target.value || null)}
            >
              <option value="">All statuses</option>
              {(Object.keys(REQUEST_STATUS) as RequestStatus[]).map((s) => (
                <option key={s} value={s}>
                  {REQUEST_STATUS[s][0]}
                </option>
              ))}
            </select>
            <label className="flex items-center gap-1.5 text-sm">
              <input type="checkbox" checked={mine} onChange={(e) => set("mine", e.target.checked ? "true" : null)} />
              Mine only
            </label>
            <Button size="sm" asChild>
              <Link to="/finance-pod/requests/new">
                <Plus aria-hidden /> New request
              </Link>
            </Button>
          </div>
        }
      >
        {requests.isPending ? (
          <Loading what="requests" />
        ) : requests.isError ? (
          <LoadError what="requests" />
        ) : requests.data.length === 0 ? (
          <Empty>No purchase requests{status ? " with this status" : " yet"}.</Empty>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead className="text-left text-xs text-muted-foreground">
                <tr className="border-b border-border">
                  <th className="py-2 pr-3 font-medium">Request</th>
                  <th className="py-2 pr-3 font-medium">Status</th>
                  <th className="py-2 pr-3 font-medium">Requester</th>
                  <th className="py-2 pr-3 font-medium">Cost centre</th>
                  <th className="py-2 pr-3 font-medium">Needed by</th>
                  <th className="py-2 pr-3 text-right font-medium">Total</th>
                  <th className="py-2 font-medium">Agent</th>
                </tr>
              </thead>
              <tbody>
                {requests.data.map((r) => {
                  const [label, tone] = REQUEST_STATUS[r.status]
                  return (
                    <tr key={r.id} className="border-b border-border/60 hover:bg-muted/30">
                      <td className="py-2 pr-3">
                        <Link to={`/finance-pod/requests/${r.id}`} className="font-medium text-primary hover:underline">
                          {r.reference}
                        </Link>
                        <span className="block max-w-xs truncate text-xs text-muted-foreground">{r.title}</span>
                      </td>
                      <td className="py-2 pr-3">
                        <Pill label={label} tone={tone} />
                      </td>
                      <td className="py-2 pr-3">{r.requester_name}</td>
                      <td className="py-2 pr-3">{r.cost_centre_code ?? "—"}</td>
                      <td className="py-2 pr-3">{formatDate(r.needed_by)}</td>
                      <td className="py-2 pr-3 text-right tabular-nums">{money(r.total, r.currency)}</td>
                      <td className="py-2">
                        {r.blocking_problems === null ? (
                          "—"
                        ) : r.blocking_problems === 0 ? (
                          <Pill label="Ready" tone="good" />
                        ) : (
                          <Pill label={`${r.blocking_problems} to fix`} tone="warn" />
                        )}
                      </td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
        )}
      </Card>
    </FpodPage>
  )
}
