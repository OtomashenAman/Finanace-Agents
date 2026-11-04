import { Link, useSearchParams } from "react-router"

import { Card, Empty, LoadError, Loading, Pill } from "@/features/service-pod/components/bits"
import { formatDateTime } from "@/features/service-pod/labels"
import { selectClass } from "@/features/service-pod/ui"

import { FpodPage } from "./components/fpod-page"
import { usePurchaseOrders } from "./hooks"
import { money, PO_STATUS } from "./labels"
import type { PoStatus } from "./procurement-api"

export function OrdersPage() {
  const [params, setParams] = useSearchParams()
  const status = (params.get("status") as PoStatus | null) || null
  const pos = usePurchaseOrders(status)
  return (
    <FpodPage title="Purchase orders" subtitle="Create and issue PO: every PO comes from an approved request.">
      <Card
        title="Purchase orders"
        actions={
          <select
            aria-label="Status"
            className={`${selectClass} h-9 w-auto`}
            value={status ?? ""}
            onChange={(e) => setParams(e.target.value ? { status: e.target.value } : {}, { replace: true })}
          >
            <option value="">All statuses</option>
            {(Object.keys(PO_STATUS) as PoStatus[]).map((s) => (
              <option key={s} value={s}>
                {PO_STATUS[s][0]}
              </option>
            ))}
          </select>
        }
      >
        {pos.isPending ? (
          <Loading what="purchase orders" />
        ) : pos.isError ? (
          <LoadError what="purchase orders" />
        ) : pos.data.length === 0 ? (
          <Empty>No purchase orders{status ? " with this status" : " yet"}.</Empty>
        ) : (
          <table className="w-full text-sm">
            <thead className="text-left text-xs text-muted-foreground">
              <tr className="border-b border-border">
                <th className="py-2 pr-3 font-medium">PO</th>
                <th className="py-2 pr-3 font-medium">Request</th>
                <th className="py-2 pr-3 font-medium">Vendor</th>
                <th className="py-2 pr-3 font-medium">Status</th>
                <th className="py-2 pr-3 font-medium">Issued</th>
                <th className="py-2 text-right font-medium">Total</th>
              </tr>
            </thead>
            <tbody>
              {pos.data.map((p) => (
                <tr key={p.id} className="border-b border-border/60">
                  <td className="py-2 pr-3">
                    <Link to={`/finance-pod/requests/${p.request_id}`} className="font-medium text-primary hover:underline">
                      {p.reference}
                    </Link>
                  </td>
                  <td className="py-2 pr-3">{p.request_reference}</td>
                  <td className="py-2 pr-3">{p.vendor_name}</td>
                  <td className="py-2 pr-3">
                    <Pill label={PO_STATUS[p.status][0]} tone={PO_STATUS[p.status][1]} />
                  </td>
                  <td className="py-2 pr-3">{p.issued_at ? formatDateTime(p.issued_at) : "—"}</td>
                  <td className="py-2 text-right tabular-nums">{money(p.total, p.currency)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </Card>
    </FpodPage>
  )
}
