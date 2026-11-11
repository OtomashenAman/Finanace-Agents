import { Card, LoadError, Loading } from "@/features/service-pod/components/bits"

import { FpodPage } from "./components/fpod-page"
import { useBillingMeasures, useClientMeasures, useInvoiceMeasures, useMeasures, usePaymentMeasures } from "./hooks"
import { ISSUE_KIND, money } from "./labels"

const days = (v: number | null) => (v === null ? "—" : `${v.toLocaleString(undefined, { maximumFractionDigits: 1 })} d`)

function Stat({ label, value, hint }: { label: string; value: string; hint: string }) {
  return (
    <div className="rounded-xl border border-border/80 bg-card p-4">
      <p className="text-xs text-muted-foreground">{label}</p>
      <p className="mt-1 text-3xl font-semibold tabular-nums">{value}</p>
      <p className="mt-1 text-xs text-muted-foreground">{hint}</p>
    </div>
  )
}

function InvoiceMeasures() {
  const q = useInvoiceMeasures()
  if (q.isPending) return <Loading what="invoice measures" />
  if (q.isError) return <LoadError what="invoice measures" />
  const d = q.data
  const maxAge = Math.max(1, ...Object.values(d.exception_ageing))
  return (
    <section className="space-y-4">
      <h2 className="text-sm font-semibold tracking-wider text-muted-foreground uppercase">Invoices · processing & matching</h2>
      <div className="grid gap-4 sm:grid-cols-3">
        <Stat
          label="First-pass match rate"
          value={d.first_pass_rate === null ? "—" : `${Math.round(d.first_pass_rate * 100)}%`}
          hint={`${d.first_pass_matched} of ${d.first_pass_judged} invoices matched on the first run`}
        />
        <Stat
          label="Open exceptions"
          value={String(d.exceptions_open)}
          hint={d.oldest_open_days !== null ? `oldest ${days(d.oldest_open_days)}` : "none waiting"}
        />
        <Stat label="Duplicates stopped" value={String(d.duplicates_stopped)} hint={`${Number(d.duplicates_amount).toLocaleString()} not paid twice`} />
      </div>
      <div className="grid gap-5 lg:grid-cols-2">
        <Card title="Exception ageing" hint="Open exceptions by age.">
          <ul className="space-y-2 text-sm">
            {Object.entries(d.exception_ageing).map(([bucket, n]) => (
              <li key={bucket} className="grid grid-cols-[110px_1fr_40px] items-center gap-3">
                <span>{bucket}</span>
                <span className="h-2.5 rounded-full bg-muted">
                  <span className="block h-2.5 rounded-full bg-amber-500" style={{ width: `${(n / maxAge) * 100}%` }} />
                </span>
                <span className="text-right tabular-nums">{n}</span>
              </li>
            ))}
          </ul>
        </Card>
        <Card title="Why invoices don't match" hint="Open exceptions by cause.">
          {Object.keys(d.exceptions_by_kind).length === 0 ? (
            <p className="text-sm text-muted-foreground">No open exceptions.</p>
          ) : (
            <ul className="space-y-1 text-sm">
              {Object.entries(d.exceptions_by_kind).map(([k, n]) => (
                <li key={k} className="flex justify-between border-b border-border/50 py-1">
                  <span>{ISSUE_KIND[k] ?? k}</span>
                  <span className="font-semibold tabular-nums">{n}</span>
                </li>
              ))}
            </ul>
          )}
        </Card>
      </div>
    </section>
  )
}

function PaymentMeasures() {
  const q = usePaymentMeasures()
  if (q.isPending) return <Loading what="payment measures" />
  if (q.isError) return <LoadError what="payment measures" />
  const d = q.data
  return (
    <section className="space-y-4">
      <h2 className="text-sm font-semibold tracking-wider text-muted-foreground uppercase">Payments · vendor support</h2>
      <div className="grid gap-4 sm:grid-cols-3">
        <Stat
          label="On-time payment rate"
          value={d.on_time_rate === null ? "—" : `${Math.round(d.on_time_rate * 100)}%`}
          hint={`${d.on_time} of ${d.payments} paid by the due date`}
        />
        <Stat label="Discounts captured" value={money(d.discounts_captured)} hint={`${d.discounts_taken_count} taken, ${d.discounts_missed_count} missed`} />
        <Stat
          label="Query response time (median)"
          value={d.median_response_minutes === null ? "—" : `${d.median_response_minutes} min`}
          hint={`${d.queries_answered_by_agent} answered by the vendor agent · ${d.queries_open} with an analyst`}
        />
      </div>
    </section>
  )
}

function ClientMeasures() {
  const q = useClientMeasures()
  if (q.isPending) return <Loading what="client measures" />
  if (q.isError) return <LoadError what="client measures" />
  const d = q.data
  return (
    <section className="space-y-4">
      <h2 className="text-sm font-semibold tracking-wider text-muted-foreground uppercase">Receivables · client set-up</h2>
      <div className="grid gap-4 sm:grid-cols-3">
        <Stat
          label="Account set-up time (median)"
          value={days(d.setup_days_median)}
          hint={`link sent to account open · ${d.accounts} account(s); application to decision ${days(d.decision_days_median)}`}
        />
        <Stat
          label="Clean on first submission"
          value={d.first_pass_judged ? `${Math.round((d.first_pass_clean / d.first_pass_judged) * 100)}%` : "—"}
          hint={`${d.issues_caught} data issue(s) caught at intake · ${d.gaps_sent} gap email(s) sent`}
        />
        <Stat
          label="Data errors after set-up"
          value={String(d.sync_fixes)}
          hint={`lab records corrected from the ERP · ${d.controller_changes} proposal(s) changed by the controller · ${d.reviews_open} review(s) waiting`}
        />
      </div>
    </section>
  )
}

function BillingMeasures() {
  const q = useBillingMeasures()
  if (q.isPending) return <Loading what="billing measures" />
  if (q.isError) return <LoadError what="billing measures" />
  const d = q.data
  const pct = (n: number) => (d.sent ? `${Math.round((n / d.sent) * 100)}%` : "—")
  return (
    <section className="space-y-4">
      <h2 className="text-sm font-semibold tracking-wider text-muted-foreground uppercase">Receivables · billing</h2>
      <div className="grid gap-4 sm:grid-cols-3">
        <Stat label="Billing accuracy" value={pct(d.accurate)} hint={`${d.accurate} of ${d.sent} sent with no price corrected`} />
        <Stat label="Days to invoice (median)" value={days(d.days_to_invoice_median)} hint={`report issued to invoice sent · ${d.same_day} the same day`} />
        <Stat label="Straight through" value={pct(d.straight_through)} hint={`nothing flagged · ${d.in_review} with the billing analyst now`} />
      </div>
    </section>
  )
}

export function MeasuresPage() {
  const m = useMeasures()
  return (
    <FpodPage title="Measures" subtitle="How each area is doing: client set-up, paying on time, invoice matching and purchasing cycle time.">
      {m.isPending ? (
        <Loading what="the measures" />
      ) : m.isError ? (
        <LoadError what="the measures" />
      ) : (
        <div className="space-y-5">
          <ClientMeasures />
          <BillingMeasures />
          <PaymentMeasures />
          <InvoiceMeasures />
          <h2 className="text-sm font-semibold tracking-wider text-muted-foreground uppercase">Purchasing · request to PO</h2>
          <div className="grid gap-4 sm:grid-cols-3">
            <Stat label="Request-to-PO cycle time (median)" value={days(m.data.cycle.median_days)} hint={`${m.data.cycle.count} request(s) reached an issued PO`} />
            <Stat
              label="Requests needing rework"
              value={m.data.rework_rate === null ? "—" : `${Math.round(m.data.rework_rate * 100)}%`}
              hint={`${m.data.reworked} of ${m.data.submitted} submitted were queried or resubmitted`}
            />
            <Stat label="Rejected" value={String(m.data.rejected)} hint="by the budget owner or the matrix" />
          </div>

          <Card title="Where the time goes" hint="Median days per stage, over the requests that went through it.">
            {(() => {
              const max = Math.max(1, ...m.data.stages.map((s) => s.median_days ?? 0))
              return (
                <ul className="space-y-2 text-sm">
                  {m.data.stages.map((s) => (
                    <li key={s.label} className="grid grid-cols-[200px_1fr_80px] items-center gap-3">
                      <span>{s.label}</span>
                      <span className="h-2.5 rounded-full bg-muted">
                        <span
                          className="block h-2.5 rounded-full bg-primary"
                          style={{ width: `${((s.median_days ?? 0) / max) * 100}%` }}
                        />
                      </span>
                      <span className="text-right tabular-nums">
                        {days(s.median_days)} <span className="text-xs text-muted-foreground">({s.count})</span>
                      </span>
                    </li>
                  ))}
                </ul>
              )
            })()}
          </Card>

          <div className="grid gap-5 lg:grid-cols-2">
            <Card title="Waiting now" hint="How many are at each stage, and the oldest.">
              <table className="w-full text-sm">
                <tbody>
                  {m.data.waiting.map((w) => (
                    <tr key={w.stage} className="border-b border-border/50">
                      <td className="py-1.5">{w.stage}</td>
                      <td className="py-1.5 text-right font-semibold tabular-nums">{w.count}</td>
                      <td className="py-1.5 pl-3 text-right text-xs text-muted-foreground">
                        {w.oldest_days !== null ? `oldest ${days(w.oldest_days)}` : ""}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </Card>
            <Card title="POs issued by month" hint="Count and median request-to-PO days.">
              {m.data.months.length === 0 ? (
                <p className="text-sm text-muted-foreground">No POs issued yet.</p>
              ) : (
                <table className="w-full text-sm">
                  <tbody>
                    {m.data.months.map((p) => (
                      <tr key={p.month} className="border-b border-border/50">
                        <td className="py-1.5">{p.month}</td>
                        <td className="py-1.5 text-right tabular-nums">{p.pos_issued} PO(s)</td>
                        <td className="py-1.5 text-right tabular-nums">{days(p.median_cycle_days)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}
            </Card>
          </div>
        </div>
      )}
    </FpodPage>
  )
}
