import { useState, type ReactNode } from "react"
import { ChevronDown, Download, Search, Sparkles } from "lucide-react"

import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Textarea } from "@/components/ui/textarea"
import { apiDownload } from "@/lib/api"
import { cn } from "@/lib/utils"

import type { CaseDetail } from "../../api"
import { AiBadge, AiCard, Card, Empty, Pill } from "../../components/bits"
import { OwnedActions, ReviewTasks } from "../../components/case-sections"
import { TaskRow } from "../../components/case-extras"
import { TaskActions } from "../../components/task-actions"
import { useFpaCommentary, useFpaDrill } from "../../hooks"
import { formatDateTime } from "../../labels"
import { attempt, selectClass } from "../../ui"
import { useRunAction } from "../../use-run-action"
import { CheckRow } from "../shared-ui"
import { BridgeChart, TrendChart } from "./charts"
import type { FpaChange, FpaContributor, FpaFact, FpaState } from "./meta"
import { amount, blockingIssues, fpaState, marginLabel, monthLabel, pct, signed } from "./meta"

/** A figure tile sized for four across the case column (amounts stay on one line). */
export function Kpi({ label, value }: { label: string; value: string }) {
  return (
    <div className="min-w-0 rounded-lg border bg-card px-3 py-3">
      <p className="truncate text-[11px] tracking-wide text-muted-foreground uppercase">{label}</p>
      <p className="mt-1 truncate text-lg font-bold text-brand-navy tabular-nums" title={value}>
        {value}
      </p>
    </div>
  )
}

const COUNTED: Record<string, string> = {
  revenue: "Revenue",
  cost_of_services: "Cost of services",
  operating_expense: "Operating expenses",
  other_income: "Other income (not operating)",
  other_expense: "Other expense (not operating)",
}

// --- 1. period & data -------------------------------------------------------------------

export function PeriodAndData({ c }: { c: CaseDetail }) {
  const s = fpaState(c)
  const issues = blockingIssues(s)
  const missing = (period: string) => s.issues.some((i) => i.code === "missing_category" && i.detail.startsWith(period))
  return (
    <>
      <Card
        title="Period and source"
        hint={`${monthLabel(s.months[0]!)} to ${monthLabel(s.months[s.months.length - 1]!)} · ${s.basis} basis · ${s.currency}${s.business_unit ? ` · ${s.business_unit}` : " · whole company"}`}
      >
        <div className="overflow-x-auto">
          <table className="w-full min-w-[620px] text-sm">
            <thead>
              <tr className="border-b text-left text-xs text-muted-foreground uppercase">
                <th className="py-1.5 pr-3 font-semibold">Month</th>
                <th className="py-1.5 pr-3 text-right font-semibold">Revenue</th>
                <th className="py-1.5 pr-3 text-right font-semibold">Cost of services</th>
                <th className="py-1.5 pr-3 text-right font-semibold">Operating exp.</th>
                <th className="py-1.5 pr-3 text-right font-semibold">Operating profit</th>
                <th className="py-1.5 pr-3 text-right font-semibold">Margin</th>
                <th className="py-1.5 font-semibold">Evidence</th>
              </tr>
            </thead>
            <tbody className="divide-y">
              {s.metrics.map((m) => (
                <tr key={m.period}>
                  <td className="py-1.5 pr-3 font-medium">{monthLabel(m.period)}</td>
                  <td className="py-1.5 pr-3 text-right tabular-nums">{amount(m.revenue, s.currency)}</td>
                  <td className="py-1.5 pr-3 text-right tabular-nums">{amount(m.cost_of_services, s.currency)}</td>
                  <td className="py-1.5 pr-3 text-right tabular-nums">{amount(m.operating_expense, s.currency)}</td>
                  <td className="py-1.5 pr-3 text-right tabular-nums">{amount(m.operating_profit, s.currency)}</td>
                  <td className="py-1.5 pr-3 text-right tabular-nums">{marginLabel(m.margin_pct)}</td>
                  <td className="py-1.5 text-xs">
                    {missing(m.period) ? <Pill label="Category missing" tone="bad" /> : <Pill label="Income · COGS · Expense" tone="good" />}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Card>

      <Card title="Data checks" hint="Nothing missing is filled in: a category with no row, or a GL movement the transactions don't explain, blocks the sign-off.">
        <ul className="text-sm">
          <CheckRow state={s.issues.some((i) => i.code === "missing_category") ? "failed" : "done"} label="Categories">
            {s.issues.some((i) => i.code === "missing_category") ? "A month lacks a category row" : "Every month has Income, Cost of goods sold and Expense rows"}
          </CheckRow>
          <CheckRow state={s.issues.some((i) => i.code === "unexplained_delta") ? "failed" : "done"} label="Reconciliation">
            {s.issues.some((i) => i.code === "unexplained_delta")
              ? "A GL movement isn't explained by its Posted transactions"
              : "Every account's GL movement equals its Posted transactions"}
          </CheckRow>
          <CheckRow state={s.changes.every((x) => x.bridge.reconciles) ? "done" : "failed"} label="Profit bridge">
            Revenue, cost of services and operating expense changes add up to the profit change
          </CheckRow>
        </ul>
        {issues.length > 0 && (
          <ul className="mt-3 space-y-1.5 border-t pt-3 text-sm text-red-800">
            {issues.map((i) => (
              <li key={i.detail}>{i.detail}</li>
            ))}
          </ul>
        )}
        {s.caveats.length > 0 && (
          <ul className="mt-3 list-disc space-y-1 border-t pt-3 pl-5 text-xs text-amber-800">
            {s.caveats.map((cv) => (
              <li key={cv}>{cv}</li>
            ))}
          </ul>
        )}
      </Card>

      <MappingReview c={c} s={s} />
    </>
  )
}

function MappingReview({ c, s }: { c: CaseDetail; s: FpaState }) {
  const { run, pending } = useRunAction(c)
  const [note, setNote] = useState("")
  const review = s.mapping_review
  return (
    <Card title="Account mapping" hint="Where each account the figures use is counted. Review it once against the chart of accounts.">
      <table className="w-full text-sm">
        <thead>
          <tr className="border-b text-left text-xs text-muted-foreground uppercase">
            <th className="py-1.5 pr-3 font-semibold">Account</th>
            <th className="py-1.5 pr-3 font-semibold">QuickBooks type</th>
            <th className="py-1.5 font-semibold">Counted as</th>
          </tr>
        </thead>
        <tbody className="divide-y">
          {s.mapping.map((m) => (
            <tr key={m.account_id}>
              <td className="py-1.5 pr-3">
                {m.number && <span className="mr-1.5 text-muted-foreground">{m.number}</span>}
                {m.account}
              </td>
              <td className="py-1.5 pr-3 text-xs">{m.classification}</td>
              <td className="py-1.5 text-xs">{COUNTED[m.counted_as] ?? m.counted_as}</td>
            </tr>
          ))}
        </tbody>
      </table>
      {review ? (
        <p className="mt-3 border-t pt-3 text-xs text-muted-foreground">
          Reviewed by {review.by} · {formatDateTime(review.at)}
          {review.note && <> · {review.note}</>}
        </p>
      ) : (
        c.allowed_actions.confirm_mapping === null && (
          <div className="mt-3 flex gap-2 border-t pt-3">
            <Input placeholder="Note (optional)" value={note} onChange={(e) => setNote(e.target.value)} />
            <Button size="sm" variant="outline" disabled={pending} onClick={() => void run("confirm_mapping", { note: note || null }, "Mapping reviewed.")}>
              Mark reviewed
            </Button>
          </div>
        )
      )}
    </Card>
  )
}

// --- 2. trends & drivers ----------------------------------------------------------------

type View = "overview" | "revenue" | "costs" | "margin"
const VIEWS: [View, string][] = [
  ["overview", "Overview"],
  ["revenue", "Revenue drivers"],
  ["costs", "Cost drivers"],
  ["margin", "Margin bridge"],
]

export function TrendsAndDrivers({ c }: { c: CaseDetail }) {
  const s = fpaState(c)
  const [view, setView] = useState<View>("overview")
  const [pair, setPair] = useState(s.changes.length - 1)
  const change = s.changes[Math.min(pair, s.changes.length - 1)]
  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex flex-wrap gap-1.5" role="tablist" aria-label="Analysis">
          {VIEWS.map(([key, label]) => (
            <button
              key={key}
              type="button"
              role="tab"
              aria-selected={view === key}
              onClick={() => setView(key)}
              className={cn(
                "rounded-full border px-3 py-1 text-xs font-medium",
                view === key ? "border-primary bg-primary/10 text-primary" : "bg-card text-muted-foreground hover:text-foreground",
              )}
            >
              {label}
            </button>
          ))}
        </div>
        {view !== "overview" && s.changes.length > 1 && (
          <select className={cn(selectClass, "h-8 w-auto text-xs")} value={pair} onChange={(e) => setPair(Number(e.target.value))} aria-label="Months compared">
            {s.changes.map((ch, i) => (
              <option key={ch.to} value={i}>
                {monthLabel(ch.from, true)} → {monthLabel(ch.to)}
              </option>
            ))}
          </select>
        )}
      </div>
      {view === "overview" && <Overview s={s} />}
      {view === "revenue" && change && <RevenueDrivers c={c} s={s} change={change} />}
      {view === "costs" && change && <CostDrivers c={c} s={s} change={change} />}
      {view === "margin" && change && <MarginBridge s={s} change={change} />}
      {!s.commentary && <CommentaryCta c={c} />}
    </div>
  )
}

function Overview({ s }: { s: FpaState }) {
  const last = s.metrics[s.metrics.length - 1]!
  const change = s.changes[s.changes.length - 1]
  return (
    <>
      <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
        <Kpi label={`Revenue ${monthLabel(last.period, true)}`} value={amount(last.revenue, s.currency)} />
        <Kpi label="Operating costs" value={amount(last.total_operating_cost, s.currency)} />
        <Kpi label="Operating profit" value={amount(last.operating_profit, s.currency)} />
        <Kpi label="Operating margin" value={marginLabel(last.margin_pct)} />
      </div>
      <Card title="Monthly trend" hint="Hover a month for its figures. The table in step 1 has every value.">
        <TrendChart metrics={s.metrics} currency={s.currency} />
      </Card>
      {change && (
        <Card title={`${monthLabel(change.from)} → ${monthLabel(change.to)}`}>
          <dl className="grid gap-3 text-sm sm:grid-cols-3">
            <div>
              <dt className="text-xs text-muted-foreground">Revenue</dt>
              <dd className="font-semibold tabular-nums">
                {signed(change.revenue.change, s.currency)} ({pct(change.revenue.pct)})
                {change.outlier && <Pill label="Outlier ≥ 10%" tone="warn" />}
              </dd>
            </div>
            <div>
              <dt className="text-xs text-muted-foreground">Total operating cost</dt>
              <dd className="font-semibold tabular-nums">
                {signed(change.total_operating_cost.change, s.currency)} ({pct(change.total_operating_cost.pct)})
              </dd>
            </div>
            <div>
              <dt className="text-xs text-muted-foreground">Operating margin shift</dt>
              <dd className="font-semibold tabular-nums">
                {change.margin_pp_exact === null ? "undefined" : `${pct(change.margin_pp_exact, 2).replace("%", "")} pp`}
                <span className="block text-xs font-normal text-muted-foreground">
                  exact; {change.margin_pp_displayed === null ? "-" : `${pct(change.margin_pp_displayed, 1).replace("%", "")} pp`} between the rounded margins
                </span>
              </dd>
            </div>
          </dl>
        </Card>
      )}
      {s.yoy.length > 0 && (
        <Card title="Year on year" hint="Only for months whose prior-year month is in the source.">
          <ul className="divide-y text-sm">
            {s.yoy.map((y) => (
              <li key={y.period} className="flex justify-between py-1.5">
                <span>
                  {monthLabel(y.period)} vs {monthLabel(y.prior_period)}
                </span>
                <span className="font-semibold tabular-nums">{pct(y.revenue_pct)}</span>
              </li>
            ))}
          </ul>
        </Card>
      )}
    </>
  )
}

function ChangeTiles({ prior, current, change, pctValue, currency, from, to }: { prior: string; current: string; change: string; pctValue: string | null; currency: string; from: string; to: string }) {
  return (
    <div className="grid gap-3 sm:grid-cols-4">
      <Kpi label={monthLabel(from)} value={amount(prior, currency)} />
      <Kpi label={monthLabel(to)} value={amount(current, currency)} />
      <Kpi label="Change" value={signed(change, currency)} />
      <Kpi label="Change %" value={pct(pctValue)} />
    </div>
  )
}

function Contributors({ rows, currency, current }: { rows: FpaContributor[]; currency: string; current: string }) {
  const [open, setOpen] = useState<string | null>(null)
  if (!rows.length) return <Empty>No transactions moved this.</Empty>
  return (
    <ul className="divide-y">
      {rows.map((d) => (
        <li key={d.counterparty} className="py-2 text-sm">
          <button type="button" className="flex w-full items-center gap-2 text-left" onClick={() => setOpen(open === d.counterparty ? null : d.counterparty)} aria-expanded={open === d.counterparty}>
            <span className="min-w-0 flex-1 truncate font-medium">{d.counterparty}</span>
            <span className={cn("font-semibold tabular-nums", Number(d.change) < 0 && "text-red-800")}>{signed(d.change, currency)}</span>
            <ChevronDown className={cn("size-4 text-muted-foreground transition-transform", open === d.counterparty && "rotate-180")} aria-hidden />
          </button>
          {open === d.counterparty && (
            <table className="mt-2 w-full text-xs">
              <thead>
                <tr className="text-left text-muted-foreground">
                  <th className="py-1 pr-2 font-medium">Transaction</th>
                  <th className="py-1 pr-2 font-medium">Type</th>
                  <th className="py-1 pr-2 font-medium">Date</th>
                  <th className="py-1 pr-2 text-right font-medium">Amount</th>
                  <th className="py-1 font-medium">GL line</th>
                </tr>
              </thead>
              <tbody>
                {d.transactions.map((t) => (
                  <tr key={t.id} className={t.period === current ? "" : "text-muted-foreground"}>
                    <td className="py-0.5 pr-2 font-mono">{t.document_ref ?? t.id}</td>
                    <td className="py-0.5 pr-2">{t.type}</td>
                    <td className="py-0.5 pr-2">{t.date}</td>
                    <td className="py-0.5 pr-2 text-right tabular-nums">{amount(t.amount, currency)}</td>
                    <td className="py-0.5 font-mono">{t.gl_line_id ?? "-"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </li>
      ))}
    </ul>
  )
}

function EvidenceButton({ c }: { c: CaseDetail }) {
  return (
    <Button size="sm" variant="outline" onClick={() => void apiDownload(`/pod/fpa/cases/${c.id}/evidence.csv`, `${c.reference}-evidence.csv`)}>
      <Download /> Export evidence
    </Button>
  )
}

function RevenueDrivers({ c, s, change }: { c: CaseDetail; s: FpaState; change: FpaChange }) {
  const prior = s.metrics.find((m) => m.period === change.from)!
  const current = s.metrics.find((m) => m.period === change.to)!
  return (
    <>
      <ChangeTiles prior={prior.revenue} current={current.revenue} change={change.revenue.change} pctValue={change.revenue.pct} currency={s.currency} from={change.from} to={change.to} />
      <Card title="Who moved revenue" hint="Each customer's Posted invoices and credit memos this month minus last month (credit memos keep their sign)." actions={<EvidenceButton c={c} />}>
        <Contributors rows={change.revenue_drivers} currency={s.currency} current={change.to} />
        <p className="mt-2 flex justify-between border-t pt-2 text-sm font-semibold">
          <span>Net revenue change</span>
          <span className="tabular-nums">{signed(change.revenue.change, s.currency)}</span>
        </p>
      </Card>
      <Unexplained change={change} currency={s.currency} />
    </>
  )
}

function CostDrivers({ c, s, change }: { c: CaseDetail; s: FpaState; change: FpaChange }) {
  const prior = s.metrics.find((m) => m.period === change.from)!
  const current = s.metrics.find((m) => m.period === change.to)!
  const [drill, setDrill] = useState<string | null>(null)
  return (
    <>
      <ChangeTiles prior={prior.total_operating_cost} current={current.total_operating_cost} change={change.total_operating_cost.change} pctValue={change.total_operating_cost.pct} currency={s.currency} from={change.from} to={change.to} />
      <Card title="Which accounts moved costs" hint="By account, with the vendors and transactions behind each." actions={<EvidenceButton c={c} />}>
        <ul className="divide-y">
          {change.cost_drivers.map((a) => (
            <li key={a.account_id} className="py-2.5 text-sm">
              <p className="flex flex-wrap items-center gap-2">
                <span className="font-semibold">{a.account}</span>
                <span className="text-xs text-muted-foreground">{a.classification === "CostOfGoodsSold" ? "Cost of services" : "Operating expense"}</span>
                <span className="ml-auto text-xs text-muted-foreground tabular-nums">
                  {amount(a.prior, s.currency)} → {amount(a.current, s.currency)}
                </span>
                <span className={cn("w-28 text-right font-semibold tabular-nums", Number(a.change) < 0 && "text-red-800")}>{signed(a.change, s.currency)}</span>
                <Button size="sm" variant="ghost" onClick={() => setDrill(drill === a.account_id ? null : a.account_id)} aria-label={`Trace ${a.account} in the GL`}>
                  <Search />
                </Button>
              </p>
              <div className="mt-1 pl-4">
                <Contributors rows={a.contributors} currency={s.currency} current={change.to} />
              </div>
              {drill === a.account_id && <Drill caseId={c.id} accountId={a.account_id} period={change.to} currency={s.currency} />}
            </li>
          ))}
        </ul>
      </Card>
      <Unexplained change={change} currency={s.currency} />
    </>
  )
}

/** Trace one account's GL line to every transaction (any status) in the source. */
function Drill({ caseId, accountId, period, currency }: { caseId: string; accountId: string; period: string; currency: string }) {
  const { data, isPending } = useFpaDrill({ caseId, accountId, period })
  if (isPending) return <p className="mt-2 text-xs text-muted-foreground">Loading…</p>
  if (!data) return null
  return (
    <div className="mt-2 rounded-md bg-secondary/40 p-3 text-xs">
      <p className="mb-1 font-semibold">
        GL {monthLabel(period)}: {data.gl_lines.map((g) => `${g.id} ${amount(g.amount, currency)} (${g.report_id})`).join(", ") || "no line"}
      </p>
      <ul className="space-y-0.5">
        {data.transactions.map((t) => (
          <li key={t.id} className="flex gap-2">
            <span className="w-32 truncate font-mono">{t.document_ref ?? t.id}</span>
            <span className="w-24">{t.type}</span>
            <span className="flex-1 truncate">{t.counterparty}</span>
            <span className="tabular-nums">{amount(t.amount, currency)}</span>
            {t.status !== "Posted" && <Pill label={t.status} tone="warn" />}
          </li>
        ))}
      </ul>
    </div>
  )
}

function Unexplained({ change, currency }: { change: FpaChange; currency: string }) {
  if (!change.unexplained.length) return null
  return (
    <Card title="Not explained by transactions" hint="These block the sign-off until the source evidence is corrected.">
      <ul className="divide-y text-sm">
        {change.unexplained.map((u) => (
          <li key={u.account_id} className="flex justify-between py-1.5 text-red-800">
            <span>{u.account}</span>
            <span className="tabular-nums">
              GL {signed(u.gl_delta, currency)} vs transactions {signed(u.transaction_delta, currency)}
            </span>
          </li>
        ))}
      </ul>
    </Card>
  )
}

function MarginBridge({ s, change }: { s: FpaState; change: FpaChange }) {
  const prior = s.metrics.find((m) => m.period === change.from)!
  const current = s.metrics.find((m) => m.period === change.to)!
  return (
    <>
      <div className="grid gap-3 sm:grid-cols-4">
        <Kpi label="Profit change" value={signed(change.operating_profit.change, s.currency)} />
        <Kpi label="Margin shift (exact)" value={change.margin_pp_exact === null ? "undefined" : `${pct(change.margin_pp_exact, 2).replace("%", "")} pp`} />
        <Kpi label="Revenue effect" value={signed(change.bridge.revenue, s.currency)} />
        <Kpi label="Cost effect" value={signed(String(Number(change.bridge.cost_of_services) + Number(change.bridge.operating_expense)), s.currency)} />
      </div>
      <Card title="Operating profit bridge" hint={change.bridge.reconciles ? "The components add up to the profit change exactly." : "The components don't reconcile: check the source."}>
        <BridgeChart change={change} currency={s.currency} />
      </Card>
      <Card title="Margin interpretation">
        <dl className="grid gap-2 text-sm sm:grid-cols-2">
          <div>
            <dt className="text-xs text-muted-foreground">{monthLabel(change.from)} margin</dt>
            <dd className="tabular-nums">
              {amount(prior.operating_profit, s.currency)} / {amount(prior.revenue, s.currency)} = {marginLabel(prior.margin_pct)}
            </dd>
          </div>
          <div>
            <dt className="text-xs text-muted-foreground">{monthLabel(change.to)} margin</dt>
            <dd className="tabular-nums">
              {amount(current.operating_profit, s.currency)} / {amount(current.revenue, s.currency)} = {marginLabel(current.margin_pct)}
            </dd>
          </div>
        </dl>
      </Card>
    </>
  )
}

// --- 3. Finance Head sign-off ----------------------------------------------------------

function CommentaryCta({ c }: { c: CaseDetail }) {
  const draft = useFpaCommentary()
  const issues = blockingIssues(fpaState(c))
  if (c.status !== "draft") return null
  return (
    <div className="flex flex-wrap items-center gap-3 rounded-lg border border-primary/30 bg-primary/5 px-4 py-3 text-sm">
      <span className="flex-1">
        {issues.length ? "Settle the data issues before writing the commentary." : "Reviewed the figures? Draft the commentary next."}
      </span>
      <Button
        size="sm"
        disabled={draft.isPending || issues.length > 0}
        onClick={() => void attempt(() => draft.mutateAsync({ caseId: c.id, version: c.version }), "Commentary drafted: check it in the sign-off step.")}
      >
        <Sparkles /> {draft.isPending ? "Drafting…" : "Draft with AI"}
      </Button>
    </div>
  )
}

/** The cited figures under a sentence: two shown, the rest on request. */
function FactChips({ ids, facts }: { ids: string[]; facts: Map<string, FpaFact> }) {
  const [all, setAll] = useState(false)
  if (!ids.length) return null
  const shown = all ? ids : ids.slice(0, 2)
  return (
    <p className="mt-1 flex flex-wrap items-center gap-1.5">
      {shown.map((id) => {
        const f = facts.get(id)
        return (
          <span key={id} className="rounded bg-secondary px-1.5 py-0.5 text-xs" title={id}>
            {f ? `${f.label}: ${f.value}` : id}
          </span>
        )
      })}
      {ids.length > 2 && (
        <button type="button" className="text-xs text-primary hover:underline" onClick={() => setAll(!all)}>
          {all ? "less" : `+${ids.length - 2} more`}
        </button>
      )}
    </p>
  )
}

/** A card that wears the AI look when the AI wrote its content */
function Framed({ ai, badge, ...props }: { ai: boolean; badge: ReactNode; title: string; hint?: ReactNode; actions?: ReactNode; children: ReactNode }) {
  return ai ? <AiCard badge={badge} {...props} /> : <Card {...props} />
}

export function Commentary({ c, s, title = "Finance Head commentary" }: { c: CaseDetail; s: FpaState; title?: string }) {
  const draft = useFpaCommentary()
  const { run, pending } = useRunAction(c)
  const [editing, setEditing] = useState(false)
  const [text, setText] = useState("")
  const cm = s.commentary
  const facts = new Map((cm?.facts ?? []).map((f) => [f.id, f]))
  const editable = c.status === "draft"
  const issues = blockingIssues(s).length > 0

  const save = () =>
    void run(
      "set_commentary",
      { highlights: text.split("\n").map((t) => t.trim()).filter((t) => t.length >= 3).map((t) => ({ text: t, fact_ids: [] })) },
      "Commentary saved.",
    ).then((r) => r && setEditing(false))

  return (
    <Framed
      ai={cm?.by === "ai"}
      badge={<AiBadge label="AI drafted · cited" />}
      title={title}
      hint="AI findings cite the engine's facts and never state a figure themselves; the cited values are shown beside them."
      actions={
        editable &&
        !editing && (
          <div className="flex gap-2">
            <Button size="sm" variant="outline" disabled={draft.isPending || issues} onClick={() => void attempt(() => draft.mutateAsync({ caseId: c.id, version: c.version }), "Commentary drafted.")}>
              <Sparkles /> {draft.isPending ? "Drafting…" : cm ? "Redraft with AI" : "Draft with AI"}
            </Button>
            <Button
              size="sm"
              variant="ghost"
              onClick={() => {
                setText((cm?.highlights ?? []).map((h) => h.text).join("\n"))
                setEditing(true)
              }}
            >
              {cm ? "Edit by hand" : "Write by hand"}
            </Button>
          </div>
        )
      }
    >
      {editing ? (
        <div className="space-y-2">
          <Textarea rows={6} value={text} onChange={(e) => setText(e.target.value)} placeholder="One finding per line" />
          <div className="flex gap-2">
            <Button size="sm" disabled={pending || !text.trim()} onClick={save}>
              Save
            </Button>
            <Button size="sm" variant="ghost" onClick={() => setEditing(false)}>
              Cancel
            </Button>
          </div>
        </div>
      ) : !cm ? (
        <Empty>{issues ? "Settle the data issues first." : "No commentary yet: draft it with AI or write it by hand."}</Empty>
      ) : (
        <>
          <ul className="space-y-3">
            {cm.highlights.map((h, i) => (
              <li key={i} className="text-sm">
                <p>{h.text}</p>
                <FactChips ids={h.fact_ids} facts={facts} />
              </li>
            ))}
          </ul>
          <p className="mt-3 border-t pt-2 text-xs text-muted-foreground">
            {cm.by === "ai" ? `Drafted by AI (${cm.provenance?.model ?? "model"}, ${cm.provenance?.prompt_version ?? ""})` : `Written by ${cm.author ?? "hand"}`} · {formatDateTime(cm.written_at)}
          </p>
        </>
      )}
    </Framed>
  )
}

/** A week from now (YYYY-MM-DD): an adopted follow-up's due date */
function inAWeek(): string {
  return new Date(Date.now() + 7 * 86_400_000).toISOString().slice(0, 10)
}

const FOLLOW_UP: Record<string, [string, "info" | "warn" | "neutral"]> = {
  question: ["Question", "info"],
  validate: ["Validate", "info"],
  investigate: ["Investigate", "warn"],
}

/** The AI's open questions and checks: they don't block the sign-off; one can be tracked as
 *  an owned action. */
export function FollowUps({ c, s }: { c: CaseDetail; s: FpaState }) {
  const { run, pending } = useRunAction(c)
  const items = (s.follow_ups ?? s.recommended_actions ?? []).filter((f) => f.kind !== "approve")
  if (!items.length) return null
  const taken = new Set(c.owned_actions.map((a) => a.title))
  return (
    <AiCard badge={<AiBadge label="AI suggestions" />} title="Questions and follow-ups" hint="From the AI, for the reviewers. They don't block the sign-off; track one if someone should act on it.">
      <ul className="divide-y">
        {items.map((r) => {
          const [label, tone] = FOLLOW_UP[r.kind] ?? ["Follow-up", "neutral"]
          return (
            <li key={r.text} className="flex items-center gap-2 py-2 text-sm">
              <Pill label={label} tone={tone} />
              <span className="flex-1">{r.text}</span>
              {taken.has(r.text.slice(0, 200)) ? (
                <span className="text-xs text-muted-foreground">Tracked</span>
              ) : (
                c.allowed_actions.add_action === null && (
                  <Button
                    size="sm"
                    variant="outline"
                    disabled={pending}
                    onClick={() => void run("add_action", { title: r.text.slice(0, 200), owner_id: c.owner.id, due_date: inAWeek() }, "Tracked as an action.")}
                  >
                    Track as action
                  </Button>
                )
              )}
            </li>
          )
        })}
      </ul>
    </AiCard>
  )
}

export function Corrections({ c, s }: { c: CaseDetail; s: FpaState }) {
  const { run, pending } = useRunAction(c)
  const [open, setOpen] = useState(false)
  const end = s.months[s.months.length - 1]!
  const [evidenceAccount, setEvidenceAccount] = useState("")
  const drill = useFpaDrill(evidenceAccount ? { caseId: c.id, accountId: evidenceAccount, period: end } : null)
  const [rationale, setRationale] = useState("")
  const [lines, setLines] = useState([
    { account_id: "", side: "debit", amount: "" },
    { account_id: "", side: "credit", amount: "" },
  ])
  const corrections = s.corrections ?? []
  const taskFor = (id: string) => c.posting_tasks.find((t) => t.reference === `${c.reference}-${id}`)
  const evidence = drill.data?.gl_lines[0]?.id
  const accounts = s.mapping

  return (
    <Card title="Corrections" hint="Only if the books are wrong: a balanced journal the Finance Admin posts in QuickBooks. A fresh source must prove it before the figures are recalculated.">
      {corrections.length === 0 && !open && <p className="text-sm text-muted-foreground">No correction proposed.</p>}
      <ul className="divide-y">
        {corrections.map((x) => {
          const task = taskFor(x.id)
          return (
            <li key={x.id} className="space-y-1.5 py-2.5 text-sm">
              <p className="flex flex-wrap items-center gap-2">
                <span className="font-semibold">{x.id}</span>
                <Pill label={x.status === "withdrawn" ? "Withdrawn" : task ? "Queued for posting" : "Proposed"} tone={x.status === "withdrawn" ? "neutral" : task ? "info" : "warn"} />
                <span className="text-xs text-muted-foreground">
                  {monthLabel(x.period)} · evidence {x.evidence_gl_line_id} · by {x.proposed_by}
                </span>
              </p>
              <p>{x.rationale}</p>
              <ul className="text-xs">
                {x.lines.map((l, i) => (
                  <li key={i} className="tabular-nums">
                    {accounts.find((a) => a.account_id === l.account_id)?.account ?? l.account_id}: {Number(l.debit) > 0 ? `Dr ${amount(l.debit, s.currency)}` : `Cr ${amount(l.credit, s.currency)}`}
                    {l.memo && <span className="text-muted-foreground"> · {l.memo}</span>}
                  </li>
                ))}
              </ul>
              {x.status === "proposed" && !task && c.allowed_actions.withdraw_correction === null && (
                <Button size="sm" variant="ghost" disabled={pending} onClick={() => void run("withdraw_correction", { correction_id: x.id }, "Correction withdrawn.")}>
                  Withdraw
                </Button>
              )}
              {x.status === "proposed" && !task && c.allowed_actions.queue_correction === null && (
                <Button size="sm" disabled={pending} onClick={() => void run("queue_correction", { correction_id: x.id }, "Queued for the Finance Admin to post.")}>
                  Queue for posting
                </Button>
              )}
              {task && (
                <div className="rounded-md bg-secondary/40 p-2">
                  <TaskRow t={task} />
                  <TaskActions t={task} />
                </div>
              )}
            </li>
          )
        })}
      </ul>
      {c.allowed_actions.propose_correction === null &&
        (open ? (
          <form
            className="mt-3 space-y-2 border-t pt-3"
            onSubmit={(e) => {
              e.preventDefault()
              void run(
                "propose_correction",
                {
                  period: end,
                  evidence_gl_line_id: evidence,
                  rationale,
                  lines: lines.map((l) => ({ account_id: l.account_id, [l.side]: l.amount })),
                },
                "Correction proposed.",
              ).then((r) => r && setOpen(false))
            }}
          >
            <p className="text-xs text-muted-foreground">Period: {monthLabel(end)} (the current period only)</p>
            <select className={selectClass} value={evidenceAccount} onChange={(e) => setEvidenceAccount(e.target.value)} aria-label="Evidence account">
              <option value="">GL evidence: the account that is wrong…</option>
              {accounts.map((a) => (
                <option key={a.account_id} value={a.account_id}>
                  {a.account}
                </option>
              ))}
            </select>
            {evidenceAccount && <p className="text-xs text-muted-foreground">Evidence: {evidence ?? "no GL line this month"}</p>}
            <Textarea rows={2} placeholder="Why the books are wrong (at least 20 characters)" value={rationale} onChange={(e) => setRationale(e.target.value)} />
            {lines.map((l, i) => (
              <div key={i} className="grid grid-cols-[1fr_110px_140px] gap-2">
                <select className={selectClass} value={l.account_id} onChange={(e) => setLines(lines.map((x, j) => (j === i ? { ...x, account_id: e.target.value } : x)))} aria-label={`Line ${i + 1} account`}>
                  <option value="">Account…</option>
                  {accounts.map((a) => (
                    <option key={a.account_id} value={a.account_id}>
                      {a.account}
                    </option>
                  ))}
                </select>
                <select className={selectClass} value={l.side} onChange={(e) => setLines(lines.map((x, j) => (j === i ? { ...x, side: e.target.value } : x)))} aria-label={`Line ${i + 1} side`}>
                  <option value="debit">Debit</option>
                  <option value="credit">Credit</option>
                </select>
                <Input inputMode="decimal" placeholder="Amount" value={l.amount} onChange={(e) => setLines(lines.map((x, j) => (j === i ? { ...x, amount: e.target.value } : x)))} />
              </div>
            ))}
            <div className="flex gap-2">
              <Button type="button" size="sm" variant="ghost" onClick={() => setLines([...lines, { account_id: "", side: "debit", amount: "" }])}>
                + Line
              </Button>
              <Button type="submit" size="sm" disabled={pending || !evidence || rationale.trim().length < 20 || lines.some((l) => !l.account_id || !l.amount)}>
                Propose
              </Button>
              <Button type="button" size="sm" variant="ghost" onClick={() => setOpen(false)}>
                Cancel
              </Button>
            </div>
          </form>
        ) : (
          <Button size="sm" variant="ghost" className="mt-2 px-0 text-primary" onClick={() => setOpen(true)}>
            + Propose a correction
          </Button>
        ))}
    </Card>
  )
}

function Exports({ c }: { c: CaseDetail }) {
  const signed = ["approved", "completed"].includes(c.status) && c.approvals.some((a) => a.valid)
  return (
    <Card title="Export">
      <div className="flex flex-wrap gap-2">
        <Button size="sm" variant="outline" onClick={() => void apiDownload(`/pod/fpa/cases/${c.id}/evidence.csv`, `${c.reference}-evidence.csv`)}>
          <Download /> Evidence (CSV)
        </Button>
        <span title={signed ? undefined : "Available once the Finance Head has signed off"} className="inline-flex">
          <Button size="sm" variant="outline" disabled={!signed} onClick={() => void apiDownload(`/pod/fpa/cases/${c.id}/pack.json`, `${c.reference}-pack.json`)}>
            <Download /> Approved pack (JSON)
          </Button>
        </span>
      </div>
    </Card>
  )
}

export function SignOff({ c }: { c: CaseDetail }) {
  const s = fpaState(c)
  return (
    <>
      <Commentary c={c} s={s} />
      <FollowUps c={c} s={s} />
      {/* Only what really needs settling (or tracking): no empty cards */}
      {c.review_tasks.length > 0 && <ReviewTasks c={c} />}
      {c.owned_actions.length > 0 && <OwnedActions c={c} />}
      <Corrections c={c} s={s} />
      <Exports c={c} />
    </>
  )
}
