import { Link } from "react-router"

import { Card, Empty, LoadError, Loading } from "@/features/service-pod/components/bits"
import { formatDateTime } from "@/features/service-pod/labels"

import { FpodPage } from "./components/fpod-page"
import { useApprovals } from "./hooks"
import { formatDate, money } from "./labels"

/** purchase requests whose current approval step you can decide now. */
export function ApprovalsPage() {
  const approvals = useApprovals()
  return (
    <FpodPage
      title="Approvals"
      subtitle="Purchase requests waiting for your decision as budget owner or under the authority matrix, oldest first."
    >
      <Card title="Waiting for me">
        {approvals.isPending ? (
          <Loading what="approvals" />
        ) : approvals.isError ? (
          <LoadError what="approvals" />
        ) : approvals.data.length === 0 ? (
          <Empty>Nothing waits for your decision.</Empty>
        ) : (
          <ul className="divide-y divide-border/60">
            {approvals.data.map((r) => (
              <li key={r.id} className="flex flex-wrap items-center justify-between gap-2 py-2.5 text-sm">
                <span>
                  <Link to={`/finance-pod/requests/${r.id}`} className="font-medium text-primary hover:underline">
                    {r.reference}
                  </Link>{" "}
                  {r.title}
                  <span className="block text-xs text-muted-foreground">
                    {r.requester_name} · cost centre {r.cost_centre_code ?? "—"} · needed by {formatDate(r.needed_by)} ·
                    submitted {r.submitted_at ? formatDateTime(r.submitted_at) : "—"}
                  </span>
                </span>
                <span className="font-semibold tabular-nums">{money(r.total, r.currency)}</span>
              </li>
            ))}
          </ul>
        )}
      </Card>
    </FpodPage>
  )
}
