import { useState } from "react"
import { Link } from "react-router"
import { Download } from "lucide-react"

import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { apiDownload } from "@/lib/api"
import { cn } from "@/lib/utils"

import type { CaseDetail } from "../../api"
import { Card, Empty, Pill } from "../../components/bits"
import { OwnedActions } from "../../components/case-sections"
import { formatDateTime } from "../../labels"
import { selectClass } from "../../ui"
import { useRunAction } from "../../use-run-action"
import { CheckRow } from "../shared-ui"
import { amount, signed } from "../fpa-trend/meta"
import { Kpi } from "../fpa-trend/step-bodies"
import { CashChart } from "./chart"
import type { ScenarioName, TreasuryReceipt, TreasuryState } from "./meta"
import { SCENARIO_LABEL, treasuryState } from "./meta"

// --- 1. opening cash -----------------------------------------------------------------------

export function OpeningCash({ c }: { c: CaseDetail }) {
  const s = treasuryState(c)
  const cash = s.cash
  const has = (code: string) => s.issues.some((i) => i.code === code)
  return (
    <Card title="Opening cash" hint="Bank-verified: cleared, dated to the snapshot, and equal to both QuickBooks balances. Nothing is inferred.">
      <div className="mb-3 grid gap-3 sm:grid-cols-3">
        <Kpi label="Cleared bank balance" value={amount(cash.bank_balance, s.currency)} />
        <Kpi label="Policy buffer" value={amount(cash.policy_buffer, s.currency)} />
        <Kpi label="Opening headroom" value={signed(String(Number(cash.bank_balance) - Number(cash.policy_buffer)), s.currency)} />
      </div>
      <ul className="text-sm">
        <CheckRow state={has("cash_not_cleared") ? "failed" : "done"} label="Cleared">
          {cash.cleared ? "Cleared funds only" : "Not cleared"}
          {cash.proof_reference && ` · ${cash.proof_reference}`}
        </CheckRow>
        <CheckRow state={has("cash_date") ? "failed" : "done"} label="Dated">
          Cash as of {cash.as_of}; forecast from {s.as_of}
        </CheckRow>
        <CheckRow state={has("cash_vs_quickbooks") ? "failed" : "done"} label="QuickBooks cash">
          {amount(cash.quickbooks_cash_balance, s.currency)}
        </CheckRow>
        <CheckRow state={has("cash_vs_reconciliation") ? "failed" : "done"} label="Reconciliation">
          {amount(cash.reconciliation_balance, s.currency)} (stated by the source, never defaulted)
        </CheckRow>
      </ul>
      {s.issues.length > 0 && (
        <ul className="mt-3 space-y-1.5 border-t pt-3 text-sm text-red-800">
          {s.issues.map((i) => (
            <li key={i.code}>{i.detail}</li>
          ))}
        </ul>
      )}
    </Card>
  )
}

// --- 2. receipts and outflows ------------------------------------------------------------

function ReceiptRow({ c, r, currency }: { c: CaseDetail; r: TreasuryReceipt; currency: string }) {
  const { run, pending } = useRunAction(c)
  const [prob, setProb] = useState(r.review ? String(Math.round(Number(r.review.probability) * 100)) : "100")
  const [why, setWhy] = useState(r.review?.rationale ?? "")
  const editable = c.allowed_actions.review_receipt === null && !r.rejected
  const p = Number(prob) / 100
  return (
    <li className="space-y-1.5 py-2.5 text-sm">
      <p className="flex flex-wrap items-center gap-2">
        <span className="font-semibold">{r.invoice_number}</span>
        <span>{r.customer}</span>
        <span className="text-muted-foreground">· {r.date}</span>
        <span className="ml-auto font-semibold tabular-nums">{amount(r.amount, currency)}</span>
        {r.rejected ? (
          <Pill label="Rejected" tone="bad" />
        ) : r.review ? (
          <Pill label={r.review.include ? `Included · ${Math.round(Number(r.review.probability) * 100)}%` : "Left out"} tone={r.review.include ? "good" : "neutral"} />
        ) : (
          <Pill label="To review" tone="warn" />
        )}
      </p>
      <p className="text-xs text-muted-foreground">
        Promise from{" "}
        <Link to={`/pod/cases/${r.case_id}`} className="text-primary hover:underline">
          {r.case_reference}
        </Link>
        {r.quote && <> · “{r.quote}”</>}
        {r.review && <> · reviewed by {r.review.by}{r.review.rationale && `: ${r.review.rationale}`}</>}
      </p>
      {r.rejected && <p className="text-xs text-red-800">{r.rejected}</p>}
      {editable && (
        <div className="flex flex-wrap items-center gap-2">
          <label className="flex items-center gap-1 text-xs">
            Probability
            <Input className="h-8 w-16" inputMode="numeric" value={prob} onChange={(e) => setProb(e.target.value.replace(/[^0-9]/g, "").slice(0, 3))} aria-label={`Probability for ${r.invoice_number} ${r.date}`} />%
          </label>
          {p < 1 && <Input className="h-8 min-w-48 flex-1" placeholder="Why below certain (at least 10 characters)" value={why} onChange={(e) => setWhy(e.target.value)} />}
          <Button
            size="sm"
            disabled={pending || !(p >= 0 && p <= 1) || (p < 1 && why.trim().length < 10)}
            onClick={() => void run("review_receipt", { receipt_id: r.id, include: true, probability: p.toFixed(4), rationale: p < 1 ? why : null }, "Tranche included.")}
          >
            Include
          </Button>
          <Button size="sm" variant="outline" disabled={pending} onClick={() => void run("review_receipt", { receipt_id: r.id, include: false }, "Tranche left out.")}>
            Leave out
          </Button>
        </div>
      )}
    </li>
  )
}

export function ReceiptsAndOutflows({ c }: { c: CaseDetail }) {
  const s = treasuryState(c)
  const approved = s.outflows.filter((o) => o.approved)
  return (
    <>
      <Card
        title="Expected receipts"
        hint="Customer promises approved in AR Collections, reviewed again here. Expected = amount × probability. A promise never books cash: actual receipts go through bank verification."
      >
        {s.receipts.length === 0 ? (
          <Empty>
            No approved promises on this entity yet. Ask customers for dates in{" "}
            <Link to="/pod/ar" className="text-primary hover:underline">
              AR Collections
            </Link>
            .
          </Empty>
        ) : (
          <ul className="divide-y">
            {s.receipts.map((r) => (
              <ReceiptRow key={r.id} c={c} r={r} currency={s.currency} />
            ))}
          </ul>
        )}
        <p className="mt-2 border-t pt-2 text-xs text-muted-foreground">
          Need a date confirmed? Open the customer's case in{" "}
          <Link to="/pod/ar" className="text-primary hover:underline">
            AR Collections
          </Link>{" "}
          and send the payment schedule request; an approved reply comes back here on refresh.
        </p>
      </Card>
      <Card title="Outflows" hint="Only approved outflows count; the app never pays, reschedules or funds anything.">
        <ul className="divide-y text-sm">
          {s.outflows.map((o) => (
            <li key={o.id} className={cn("flex flex-wrap items-center gap-2 py-2", !o.approved && "text-muted-foreground")}>
              <span className="font-medium">{o.category}</span>
              <span className="text-xs">· {o.date}</span>
              {o.approval_ref && <span className="text-xs text-muted-foreground">· {o.approval_ref}</span>}
              <span className="ml-auto tabular-nums">{amount(o.amount, s.currency)}</span>
              <Pill label={o.approved ? "Approved" : "Not approved: left out"} tone={o.approved ? "good" : "neutral"} />
            </li>
          ))}
        </ul>
        <p className="mt-2 border-t pt-2 text-sm font-semibold">
          Approved total {amount(String(approved.reduce((t, o) => t + Number(o.amount), 0)), s.currency)}
        </p>
      </Card>
    </>
  )
}

// --- 3. forecast and scenarios -----------------------------------------------------------

function ScenarioEditor({ c, s }: { c: CaseDetail; s: TreasuryState }) {
  const { run, pending } = useRunAction(c)
  const [scenario, setScenario] = useState<"optimistic" | "stress">("stress")
  const [event, setEvent] = useState("")
  const [amt, setAmt] = useState("")
  const [to, setTo] = useState("")
  const [note, setNote] = useState("")
  const events = [
    ...s.receipts.filter((r) => !r.rejected && r.review?.include).map((r) => ({ id: r.id, label: `Receipt ${r.invoice_number} ${r.date} (${amount(r.amount, s.currency)})` })),
    ...s.outflows.filter((o) => o.approved).map((o) => ({ id: o.id, label: `Outflow ${o.category} ${o.date} (${amount(o.amount, s.currency)})` })),
  ]
  const editable = c.allowed_actions.add_shift === null
  return (
    <Card title="Scenario shifts" hint="Optimistic and Stress move part of an existing receipt or outflow to an explicit date, with a reason. Moving within the 13 weeks changes timing, never the total.">
      {(["optimistic", "stress"] as const).map((name) => (
        <div key={name} className="mb-2">
          <p className="text-xs font-semibold text-brand-navy uppercase">{SCENARIO_LABEL[name]}</p>
          {(s.scenarios?.[name] ?? []).length === 0 ? (
            <p className="text-xs text-muted-foreground">Same as Base.</p>
          ) : (
            <ul className="text-sm">
              {s.scenarios![name]!.map((sh) => (
                <li key={sh.id} className="flex flex-wrap items-center gap-2 py-1">
                  <span className="tabular-nums">{amount(sh.amount, s.currency)}</span>
                  <span className="text-muted-foreground">
                    of {sh.event_id.length > 12 ? sh.kind : sh.event_id} from {sh.from_date} to {sh.to_date}: {sh.note}
                  </span>
                  {editable && (
                    <Button size="sm" variant="ghost" className="ml-auto" disabled={pending} onClick={() => void run("remove_shift", { scenario: name, shift_id: sh.id }, "Shift removed.")}>
                      Remove
                    </Button>
                  )}
                </li>
              ))}
            </ul>
          )}
        </div>
      ))}
      {editable && events.length > 0 && (
        <form
          className="mt-3 grid gap-2 border-t pt-3 sm:grid-cols-[130px_1fr_120px_150px]"
          onSubmit={(e) => {
            e.preventDefault()
            void run("add_shift", { scenario, event_id: event, amount: amt, to_date: to, note }, "Shift added.").then((r) => {
              if (r) {
                setAmt("")
                setNote("")
              }
            })
          }}
        >
          <select className={selectClass} value={scenario} onChange={(e) => setScenario(e.target.value as "optimistic" | "stress")} aria-label="Scenario">
            <option value="stress">Stress</option>
            <option value="optimistic">Optimistic</option>
          </select>
          <select className={selectClass} value={event} onChange={(e) => setEvent(e.target.value)} aria-label="Event to move">
            <option value="">Event to move…</option>
            {events.map((ev) => (
              <option key={ev.id} value={ev.id}>
                {ev.label}
              </option>
            ))}
          </select>
          <Input inputMode="decimal" placeholder="Amount" value={amt} onChange={(e) => setAmt(e.target.value)} />
          <Input type="date" value={to} onChange={(e) => setTo(e.target.value)} aria-label="New date" />
          <Input className="sm:col-span-3" placeholder="Why (at least 20 characters)" value={note} onChange={(e) => setNote(e.target.value)} />
          <Button type="submit" size="sm" disabled={pending || !event || !amt || !to || note.trim().length < 20}>
            Add shift
          </Button>
        </form>
      )}
    </Card>
  )
}

export function Forecast({ c }: { c: CaseDetail }) {
  const s = treasuryState(c)
  const [view, setView] = useState<ScenarioName>("base")
  const r = s.results[view]
  const gap = Number(r.ending_cash) - Number(r.buffer)
  return (
    <>
      <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
        <Kpi label="Closing cash (base)" value={amount(s.results.base.ending_cash, s.currency)} />
        <Kpi label="Required buffer" value={amount(s.results.base.buffer, s.currency)} />
        <Kpi label="Gap at day 91" value={signed(String(Number(s.results.base.ending_cash) - Number(s.results.base.buffer)), s.currency)} />
        <Kpi label="Forecast status" value={s.results.base.first_breach ? `At risk from ${s.results.base.first_breach}` : "Within buffer"} />
      </div>
      <Card
        title="13-week cash"
        hint="Daily cash = prior cash + expected receipts − approved outflows. Hover a day for each scenario."
        actions={
          <Button size="sm" variant="outline" onClick={() => void apiDownload(`/pod/treasury/cases/${c.id}/forecast.csv`, `${c.reference}-cash-forecast.csv`)}>
            <Download /> Export cash report
          </Button>
        }
      >
        <CashChart results={s.results} currency={s.currency} />
      </Card>
      <Card title="Scenarios" hint="Ending cash, the lowest point and the first breach of the buffer in each.">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b text-left text-xs text-muted-foreground uppercase">
              <th className="py-1.5 pr-3 font-semibold">Scenario</th>
              <th className="py-1.5 pr-3 text-right font-semibold">Ending cash</th>
              <th className="py-1.5 pr-3 text-right font-semibold">Lowest</th>
              <th className="py-1.5 pr-3 text-right font-semibold">Largest shortfall</th>
              <th className="py-1.5 font-semibold">First breach</th>
            </tr>
          </thead>
          <tbody className="divide-y">
            {(["optimistic", "base", "stress"] as const).map((name) => {
              const x = s.results[name]
              return (
                <tr key={name}>
                  <td className="py-1.5 pr-3 font-medium">{SCENARIO_LABEL[name]}</td>
                  <td className="py-1.5 pr-3 text-right tabular-nums">{amount(x.ending_cash, s.currency)}</td>
                  <td className="py-1.5 pr-3 text-right tabular-nums">{amount(x.minimum_cash, s.currency)}</td>
                  <td className={cn("py-1.5 pr-3 text-right tabular-nums", Number(x.max_shortfall) > 0 && "text-red-800")}>{amount(x.max_shortfall, s.currency)}</td>
                  <td className="py-1.5">{x.first_breach ?? "None"}</td>
                </tr>
              )
            })}
          </tbody>
        </table>
      </Card>
      <Card
        title="Weekly view"
        hint={`${r.start} to ${r.end} · ${SCENARIO_LABEL[view]}`}
        actions={
          <select className={cn(selectClass, "h-8 w-auto text-xs")} value={view} onChange={(e) => setView(e.target.value as ScenarioName)} aria-label="Scenario shown">
            {(["base", "optimistic", "stress"] as const).map((n) => (
              <option key={n} value={n}>
                {SCENARIO_LABEL[n]}
              </option>
            ))}
          </select>
        }
      >
        <div className="overflow-x-auto">
          <table className="w-full min-w-[600px] text-sm">
            <thead>
              <tr className="border-b text-left text-xs text-muted-foreground uppercase">
                <th className="py-1.5 pr-3 font-semibold">Week</th>
                <th className="py-1.5 pr-3 text-right font-semibold">Inflow</th>
                <th className="py-1.5 pr-3 text-right font-semibold">Outflow</th>
                <th className="py-1.5 pr-3 text-right font-semibold">Ending cash</th>
                <th className="py-1.5 pr-3 text-right font-semibold">Lowest</th>
                <th className="py-1.5 text-right font-semibold">Shortfall</th>
              </tr>
            </thead>
            <tbody className="divide-y">
              {r.weeks.map((w) => (
                <tr key={w.week} className={Number(w.max_shortfall) > 0 ? "bg-red-50/60 dark:bg-red-950/20" : ""}>
                  <td className="py-1 pr-3">
                    {w.week} <span className="text-xs text-muted-foreground">{w.from.slice(5)}–{w.to.slice(5)}</span>
                  </td>
                  <td className="py-1 pr-3 text-right tabular-nums">{Number(w.inflow) ? amount(w.inflow, s.currency) : "-"}</td>
                  <td className="py-1 pr-3 text-right tabular-nums">{Number(w.outflow) ? amount(w.outflow, s.currency) : "-"}</td>
                  <td className="py-1 pr-3 text-right tabular-nums">{amount(w.ending_cash, s.currency)}</td>
                  <td className="py-1 pr-3 text-right tabular-nums">{amount(w.minimum_cash, s.currency)}</td>
                  <td className={cn("py-1 text-right tabular-nums", Number(w.max_shortfall) > 0 && "font-semibold text-red-800")}>
                    {Number(w.max_shortfall) ? amount(w.max_shortfall, s.currency) : "-"}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <p className="mt-2 border-t pt-2 text-xs text-muted-foreground">
          Bridge: opening {amount(r.opening, s.currency)} + receipts {amount(r.inflow, s.currency)} − outflows {amount(r.outflow, s.currency)} = {amount(r.ending_cash, s.currency)} ({gap >= 0 ? "above" : "below"} the buffer by {amount(String(Math.abs(gap)), s.currency)})
        </p>
      </Card>
      <ScenarioEditor c={c} s={s} />
    </>
  )
}

// --- 4. mitigation and CFO -------------------------------------------------------------

export function MitigationAndCfo({ c }: { c: CaseDetail }) {
  const s = treasuryState(c)
  const base = s.results.base
  return (
    <>
      {base.first_breach ? (
        <Card title="Buffer breach" hint="A breach anywhere in the 13 weeks, even one that recovers, needs an owned mitigation (who, by when, outcome) before the sign-offs.">
          <p className="text-sm text-red-800">
            Cash falls below the {amount(base.buffer, s.currency)} buffer from {base.first_breach}; the largest shortfall is {amount(base.max_shortfall, s.currency)}.
          </p>
          <p className="mt-1 text-xs text-muted-foreground">The app never pays, reschedules or funds anything: mitigations are actions people take.</p>
        </Card>
      ) : (
        <Card title="Buffer">
          <p className="text-sm">Base cash stays above the buffer for all 13 weeks.</p>
        </Card>
      )}
      <OwnedActions c={c} />
      <Card title="Approval record" hint="The Treasury Head approves the assumptions and results; the CFO gives the final cash-plan approval. An edit asks for both again.">
        <ul className="text-sm">
          {["Treasury Head", "CFO"].map((cap) => {
            const a = c.approvals.filter((x) => x.valid && x.capacity === cap).at(-1)
            return (
              <CheckRow key={cap} state={a ? "done" : c.next_signoff === cap ? "waiting" : "na"} label={cap}>
                {a ? `Signed off by ${a.user.name} · ${formatDateTime(a.created_at)}` : c.next_signoff === cap ? "Waiting for this sign-off" : "After the Treasury Head"}
              </CheckRow>
            )
          })}
        </ul>
      </Card>
    </>
  )
}
