import { Link } from "react-router"
import { FileText } from "lucide-react"

import { Pill } from "@/features/service-pod/components/bits"

import { useInvoices } from "../hooks"
import { formatDate, INVOICE_STATUS, money } from "../labels"
import type { PurchaseOrder } from "../procurement-api"

/** Phase 3 on the PO: every invoice billed against it, and how much of the PO is billed. */
export function PoInvoices({ po }: { po: PurchaseOrder }) {
  const invoices = useInvoices(null, po.id)
  const list = invoices.data ?? []
  const live = list.filter((i) => !["rejected", "duplicate", "captured"].includes(i.status))
  const billed = live.reduce((s, i) => s + Number(i.total ?? 0), 0)
  return (
    <section aria-label="Invoices against this PO" className="space-y-2 rounded-lg border border-border p-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h3 className="flex items-center gap-1.5 font-semibold">
          <FileText className="size-4" aria-hidden /> Invoices against this PO
        </h3>
        <span className="text-xs text-muted-foreground">
          Billed {money(billed, po.currency)} of {money(po.total, po.currency)}
        </span>
      </div>
      {list.length === 0 ? (
        <p className="text-xs text-muted-foreground">
          No invoices yet. Capture one under{" "}
          <Link to="/finance-pod/invoices" className="text-primary hover:underline">
            Invoices
          </Link>{" "}
          quoting {po.reference}.
        </p>
      ) : (
        <ul className="divide-y divide-border/60 text-sm">
          {list.map((i) => (
            <li key={i.id} className="flex flex-wrap items-center justify-between gap-2 py-1.5">
              <span>
                <Link to={`/finance-pod/invoices/${i.id}`} className="font-medium text-primary hover:underline">
                  {i.reference}
                </Link>{" "}
                <span className="text-muted-foreground">
                  {i.vendor_invoice_number ?? "—"} · {formatDate(i.invoice_date)}
                </span>
              </span>
              <span className="flex items-center gap-2">
                <span className="tabular-nums">{money(i.total, i.currency)}</span>
                <Pill label={INVOICE_STATUS[i.status][0]} tone={INVOICE_STATUS[i.status][1]} />
              </span>
            </li>
          ))}
        </ul>
      )}
    </section>
  )
}
