import type { CaseDetail } from "../../api"
import { Card } from "../../components/bits"
import { money, type InvoiceState } from "../shared"
import { InvoiceTable } from "../shared-ui"

/** AR: the customer and the overdue invoices the case is about (deck AR screen 2). */
export function ArPanel({ c }: { c: CaseDetail }) {
  const s = c.state as { customer?: { name: string; email: string | null }; invoices?: InvoiceState[]; total_open?: string; currency?: string }
  const approved = c.commitments.filter((x) => x.status === "approved")
  const promised = approved.reduce((sum, x) => sum + Number(x.amount), 0)
  return (
    <Card title={s.customer?.name ?? "Customer"} hint={s.customer?.email ? `Verified contact: ${s.customer.email}` : "No verified contact in the source: mail can't be sent"}>
      <InvoiceTable rows={s.invoices ?? []} currency={s.currency} />
      <dl className="mt-3 grid grid-cols-3 gap-2 text-xs">
        <div>
          <dt className="text-muted-foreground">Total open</dt>
          <dd className="font-semibold">{money(s.total_open, s.currency)}</dd>
        </div>
        <div>
          <dt className="text-muted-foreground">Approved promises</dt>
          <dd className="font-semibold">{money(promised, s.currency)}</dd>
        </div>
        <div>
          <dt className="text-muted-foreground">Paid in QuickBooks</dt>
          <dd className="font-semibold">Promises are not receipts</dd>
        </div>
      </dl>
    </Card>
  )
}
