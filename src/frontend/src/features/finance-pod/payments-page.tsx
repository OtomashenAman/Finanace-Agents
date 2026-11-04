import { useState } from "react"
import { Link, useNavigate } from "react-router"
import { HandCoins, Sparkles, Trash2 } from "lucide-react"
import { toast } from "sonner"

import { Button } from "@/components/ui/button"
import { AiBadge, AiCard, Card, Empty, LoadError, Loading, Pill } from "@/features/service-pod/components/bits"
import { formatDateTime } from "@/features/service-pod/labels"
import { attempt } from "@/features/service-pod/ui"
import { errorMessage } from "@/lib/api"

import { FpodPage } from "./components/fpod-page"
import { useFinanceSettings, useFpodMutation, usePaymentMeasures, usePaymentRuns } from "./hooks"
import { formatDate, money, RUN_STATUS } from "./labels"
import { paymentsApi } from "./payments-api"

function Kpis() {
  const m = usePaymentMeasures().data
  if (!m) return null
  const tiles = [
    { label: "On-time payment rate", value: m.on_time_rate === null ? "—" : `${Math.round(m.on_time_rate * 100)}%`, hint: `${m.on_time} of ${m.payments} paid by the due date` },
    { label: "Discounts captured", value: money(m.discounts_captured), hint: `${m.discounts_taken_count} taken, ${m.discounts_missed_count} missed` },
    { label: "Query response time", value: m.median_response_minutes === null ? "—" : `${m.median_response_minutes} min`, hint: `median · ${m.queries_answered_by_agent} answered by the agent` },
    { label: "Queries with an analyst", value: String(m.queries_open), hint: "disputes and escalations" },
  ]
  return (
    <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
      {tiles.map((t) => (
        <div key={t.label} className="rounded-xl border border-border/80 bg-card p-4">
          <p className="text-xs text-muted-foreground">{t.label}</p>
          <p className="mt-1 text-2xl font-semibold tabular-nums">{t.value}</p>
          <p className="mt-1 text-xs text-muted-foreground">{t.hint}</p>
        </div>
      ))}
    </div>
  )
}

export function PaymentsPage() {
  const navigate = useNavigate()
  const runs = usePaymentRuns()
  const settings = useFinanceSettings().data
  const propose = useFpodMutation(paymentsApi.propose)
  const remove = useFpodMutation(paymentsApi.remove)
  const [picked, setPicked] = useState<Set<string>>(new Set())
  const all = runs.data ?? []
  const toggle = (id: string) =>
    setPicked((p) => {
      const next = new Set(p)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      return next
    })
  const deletePicked = async () => {
    const chosen = all.filter((r) => picked.has(r.id))
    const released = chosen.filter((r) => r.status === "released").length
    const ok = window.confirm(
      `Delete ${chosen.map((r) => r.reference).join(", ")}?` +
        (released ? `\n\nInvoices paid by ${released === 1 ? "the released run" : "the released runs"} go back to "ready to pay" so the payment agent picks them up again. Remittance emails already sent can't be recalled.` : ""),
    )
    if (!ok) return
    const r = await attempt(() => remove.mutateAsync([[...picked]]), (x) => `${x.deleted} run(s) deleted.`)
    if (r) setPicked(new Set())
  }
  const live = (runs.data ?? []).find((r) => r.status === "proposed" || r.status === "partly_approved")
  return (
    <FpodPage title="Payment runs" subtitle="The payment agent proposes; the AP analyst checks the risk flags; two people in treasury release.">
      <div className="space-y-5">
        <Kpis />
        <AiCard
          title="Next payment run"
          hint={`Approved invoices due within ${settings?.payment_horizon_days ?? 7} days, or with an early-pay discount still to take; grouped by currency and bank, with risk checks on each payment.`}
          badge={<AiBadge label="Payment agent" />}
        >
          {live ? (
            <p className="text-sm">
              <Link to={`/finance-pod/payments/${live.id}`} className="font-medium text-primary hover:underline">
                {live.reference}
              </Link>{" "}
              is waiting: {live.count} payments, {money(live.total)}. Release or cancel it before proposing another.
            </p>
          ) : (
            <Button
              disabled={propose.isPending}
              onClick={async () => {
                try {
                  const run = await propose.mutateAsync([])
                  toast.success(`The payment agent proposed ${run.reference}.`)
                  navigate(`/finance-pod/payments/${run.id}`)
                } catch (error) {
                  toast.error(errorMessage(error, "The run couldn't be proposed."))
                }
              }}
            >
              <Sparkles aria-hidden /> {propose.isPending ? "Selecting invoices…" : "Ask the payment agent for a run"}
            </Button>
          )}
        </AiCard>
        <Card
          title="Runs"
          actions={
            picked.size > 0 && (
              <Button size="sm" variant="outline" className="text-red-700" disabled={remove.isPending} onClick={() => void deletePicked()}>
                <Trash2 aria-hidden /> Delete {picked.size} selected
              </Button>
            )
          }
        >
          {runs.isPending ? (
            <Loading what="payment runs" />
          ) : runs.isError ? (
            <LoadError what="payment runs" />
          ) : runs.data.length === 0 ? (
            <Empty icon={<HandCoins className="size-5" />}>No payment runs yet.</Empty>
          ) : (
            <table className="w-full text-sm">
              <thead className="text-left text-xs text-muted-foreground">
                <tr className="border-b border-border">
                  <th className="w-8 py-2 pr-2">
                    <input
                      type="checkbox"
                      aria-label="Select all runs"
                      checked={picked.size === all.length && all.length > 0}
                      onChange={(e) => setPicked(e.target.checked ? new Set(all.map((r) => r.id)) : new Set())}
                    />
                  </th>
                  <th className="py-2 pr-3 font-medium">Run</th>
                  <th className="py-2 pr-3 font-medium">Date</th>
                  <th className="py-2 pr-3 font-medium">Status</th>
                  <th className="py-2 pr-3 text-right font-medium">Payments</th>
                  <th className="py-2 pr-3 text-right font-medium">Discounts</th>
                  <th className="py-2 text-right font-medium">Total</th>
                </tr>
              </thead>
              <tbody>
                {runs.data.map((r) => (
                  <tr key={r.id} className="border-b border-border/60 hover:bg-muted/30">
                    <td className="py-2 pr-2">
                      <input type="checkbox" aria-label={`Select ${r.reference}`} checked={picked.has(r.id)} onChange={() => toggle(r.id)} />
                    </td>
                    <td className="py-2 pr-3">
                      <Link to={`/finance-pod/payments/${r.id}`} className="font-medium text-primary hover:underline">
                        {r.reference}
                      </Link>
                      {r.flags > 0 && <span className="ml-2 text-xs text-amber-700">{r.flags} flagged</span>}
                    </td>
                    <td className="py-2 pr-3">{formatDate(r.run_date)}</td>
                    <td className="py-2 pr-3">
                      <Pill label={RUN_STATUS[r.status][0]} tone={RUN_STATUS[r.status][1]} />
                      {r.released_at && <span className="ml-1 text-xs text-muted-foreground">{formatDateTime(r.released_at)}</span>}
                    </td>
                    <td className="py-2 pr-3 text-right tabular-nums">{r.count}</td>
                    <td className="py-2 pr-3 text-right tabular-nums">{money(r.discounts)}</td>
                    <td className="py-2 text-right font-medium tabular-nums">{money(r.total)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </Card>
      </div>
    </FpodPage>
  )
}
