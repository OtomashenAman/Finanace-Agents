import { useParams } from "react-router"
import { useQuery } from "@tanstack/react-query"
import { Download, FileText } from "lucide-react"

import { Alert } from "@/components/ui/alert"
import { Button } from "@/components/ui/button"
import { errorMessage } from "@/lib/api"

import { billingApi } from "./billing-api"
import { formatDate, money } from "./labels"

/** A client's view of their invoice. No login: the link from the invoice email is the key. */
export function ClientInvoicePage() {
  const { token = "" } = useParams()
  const q = useQuery({ queryKey: ["client-invoice", token], queryFn: () => billingApi.publicInvoice(token), retry: false })
  const inv = q.data
  return (
    <div className="min-h-svh bg-brand-page px-4 py-10">
      <div className="mx-auto max-w-3xl rounded-2xl border border-border bg-card p-6 shadow-sm">
        {q.isPending ? (
          <p className="text-sm text-muted-foreground">Loading…</p>
        ) : q.isError || !inv ? (
          <Alert>{errorMessage(q.error, "This link isn't valid any more. Ask us for a copy of the invoice.")}</Alert>
        ) : (
          <div className="space-y-5">
            <div className="flex flex-wrap items-start justify-between gap-3">
              <div>
                <p className="text-sm font-medium text-muted-foreground">{inv.organisation}</p>
                <h1 className="flex items-center gap-2 text-2xl font-semibold">
                  <FileText className="size-6 text-primary" aria-hidden /> Invoice {inv.reference}
                </h1>
                <p className="text-sm text-muted-foreground">
                  {inv.client_name} · account {inv.client_code} · submission {inv.submission_reference}
                </p>
              </div>
              <Button variant="outline" onClick={() => billingApi.publicPdf(token, inv.reference)}>
                <Download aria-hidden /> Download PDF
              </Button>
            </div>
            {inv.status === "void" && <Alert>This invoice was cancelled: nothing is due on it.</Alert>}
            <dl className="grid gap-3 text-sm sm:grid-cols-3">
              <div>
                <dt className="text-xs text-muted-foreground">Invoice date</dt>
                <dd className="font-medium">{formatDate(inv.issue_date)}</dd>
              </div>
              <div>
                <dt className="text-xs text-muted-foreground">Due</dt>
                <dd className="font-medium">{formatDate(inv.due_date)}</dd>
              </div>
              <div>
                <dt className="text-xs text-muted-foreground">Terms</dt>
                <dd className="font-medium">{inv.payment_terms}</dd>
              </div>
            </dl>
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead className="text-left text-xs text-muted-foreground">
                  <tr className="border-b border-border">
                    <th className="py-2 pr-3 font-medium">Item</th>
                    <th className="py-2 pr-3 font-medium">Service</th>
                    <th className="py-2 pr-3 text-right font-medium">Qty</th>
                    <th className="py-2 pr-3 text-right font-medium">Price</th>
                    <th className="py-2 text-right font-medium">Amount</th>
                  </tr>
                </thead>
                <tbody>
                  {inv.lines.map((l, i) => (
                    <tr key={i} className="border-b border-border/60">
                      <td className="py-2 pr-3">{l.item_ref}</td>
                      <td className="py-2 pr-3">
                        {l.description}{" "}
                        <span className="text-xs text-muted-foreground">
                          ({l.stone_type}
                          {l.carat && `, ${l.carat} ct`})
                        </span>
                      </td>
                      <td className="py-2 pr-3 text-right tabular-nums">{l.quantity}</td>
                      <td className="py-2 pr-3 text-right tabular-nums">{money(l.unit_price)}</td>
                      <td className="py-2 text-right tabular-nums">{money(l.amount)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <dl className="ml-auto max-w-xs space-y-1 text-sm">
              <div className="flex justify-between">
                <dt>Subtotal</dt>
                <dd className="tabular-nums">{money(inv.subtotal, inv.currency)}</dd>
              </div>
              <div className="flex justify-between">
                <dt>
                  {inv.tax_name ?? "Tax"} ({Number(inv.tax_rate)}%)
                </dt>
                <dd className="tabular-nums">{money(inv.tax)}</dd>
              </div>
              <div className="flex justify-between border-t border-border pt-1 text-base font-semibold">
                <dt>Total due</dt>
                <dd className="tabular-nums">{money(inv.total, inv.currency)}</dd>
              </div>
            </dl>
            <p className="text-xs text-muted-foreground">Please quote {inv.reference} with your payment.</p>
          </div>
        )}
      </div>
    </div>
  )
}
