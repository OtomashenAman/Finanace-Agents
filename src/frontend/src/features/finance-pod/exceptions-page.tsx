import { Link, useSearchParams } from "react-router"

import { Card, Empty, LoadError, Loading, Pill } from "@/features/service-pod/components/bits"
import { cn } from "@/lib/utils"

import { FpodPage } from "./components/fpod-page"
import { useInvoiceExceptions } from "./hooks"
import type { ExceptionStatus } from "./invoices-api"
import { EXCEPTION_STATUS, ISSUE_KIND, money } from "./labels"

const FILTERS: (ExceptionStatus | null)[] = [null, "open", "waiting_receipt", "waiting_vendor"]

function ageTone(days: number): string {
  return days > 30 ? "bg-red-100 text-red-800" : days > 14 ? "bg-amber-100 text-amber-900" : "bg-emerald-50 text-emerald-800"
}

/** every open variance, oldest first, so nothing ages without an owner. */
export function ExceptionsPage() {
  const [params, setParams] = useSearchParams()
  const status = (params.get("status") as ExceptionStatus | null) || null
  const list = useInvoiceExceptions(status)
  return (
    <FpodPage
      title="Invoice exceptions"
      subtitle="Variances and missing receipts, oldest first. The exception agent prepared each case; the buyer or the receiver acts."
    >
      <Card
        title="Open exceptions"
        hint="Ageing: green up to 14 days, amber to 30, red after."
        actions={
          <div className="flex flex-wrap gap-1">
            {FILTERS.map((f) => (
              <button
                key={f ?? "all"}
                type="button"
                onClick={() => setParams(f ? { status: f } : {}, { replace: true })}
                className={cn(
                  "rounded-full border px-2.5 py-0.5 text-xs",
                  status === f ? "border-primary bg-primary text-primary-foreground" : "border-border hover:bg-muted",
                )}
              >
                {f ? EXCEPTION_STATUS[f][0] : "All open"}
              </button>
            ))}
          </div>
        }
      >
        {list.isPending ? (
          <Loading what="exceptions" />
        ) : list.isError ? (
          <LoadError what="exceptions" />
        ) : list.data.length === 0 ? (
          <Empty>No open exceptions: every invoice matched or was resolved.</Empty>
        ) : (
          <ul className="divide-y divide-border/60">
            {list.data.map((e) => (
              <li key={e.id} className="flex flex-wrap items-center justify-between gap-3 py-3 text-sm">
                <div className="min-w-0">
                  <Link to={`/finance-pod/invoices/${e.invoice_id}`} className="font-medium text-primary hover:underline">
                    {e.invoice_reference}
                  </Link>{" "}
                  · {e.vendor_name ?? "—"} · {e.po_reference ?? "no PO"} · {money(e.total, e.currency)}
                  <div className="mt-1 flex flex-wrap gap-1">
                    {e.kinds.map((k) => (
                      <Pill key={k} label={ISSUE_KIND[k] ?? k} tone="warn" />
                    ))}
                  </div>
                  <p className="mt-1 max-w-2xl truncate text-xs text-muted-foreground">{e.issues[0]?.message}</p>
                </div>
                <div className="flex items-center gap-2">
                  <span className={cn("rounded-md px-2 py-0.5 text-xs font-semibold tabular-nums", ageTone(e.age_days))}>
                    {e.age_days} d
                  </span>
                  <Pill label={EXCEPTION_STATUS[e.status][0]} tone={EXCEPTION_STATUS[e.status][1]} />
                </div>
              </li>
            ))}
          </ul>
        )}
      </Card>
    </FpodPage>
  )
}
