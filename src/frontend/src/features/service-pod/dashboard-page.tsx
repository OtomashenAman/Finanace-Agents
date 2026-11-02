import { useState } from "react"
import { Link } from "react-router"
import { ArrowRight, CircleAlert, CircleCheck, Mail } from "lucide-react"

import { AppPage } from "@/components/layout/app-page"
import { cn } from "@/lib/utils"

import type { Dashboard, DashboardPhase, PromiseItem } from "./api"
import { Card, Empty, LoadError, Loading, Pill, PodTabs } from "./components/bits"
import { fmt } from "./flows/shared"
import { useDashboard, useMyQueue } from "./hooks"
import { CASE_PHASE, formatDateTime, REVIEW_KIND, WORKFLOW_SHORT } from "./labels"
import { WorkflowCards } from "./workflows-page"

const PROVIDER: Record<string, string> = { microsoft: "Microsoft 365", brevo: "Brevo", outbox: "the outbox" }

const PHASES: DashboardPhase[] = ["compose", "waiting", "review", "ready", "approved", "closed"]
const PHASE_LABEL = (p: DashboardPhase) => (p === "closed" ? "Closed (30 days)" : CASE_PHASE[p][0])

function Tile({ label, value, hint, to }: { label: string; value: string; hint?: string; to?: string }) {
  const body = (
    <>
      <p className="text-xs font-medium tracking-wide text-muted-foreground uppercase">{label}</p>
      <p className="mt-1 text-2xl font-bold text-brand-navy tabular-nums">{value}</p>
      {hint && <p className="mt-0.5 text-xs text-muted-foreground">{hint}</p>}
    </>
  )
  const cls = "block rounded-lg border bg-card p-4"
  return to ? (
    <Link to={to} className={cn(cls, "transition-colors hover:border-primary/50")}>
      {body}
    </Link>
  ) : (
    <div className={cls}>{body}</div>
  )
}

/** A single-series horizontal bar: label, thin bar, the value written beside it. */
function BarRow({
  label,
  value,
  max,
  active,
  onClick,
}: {
  label: string
  value: number
  max: number
  active?: boolean
  onClick?: () => void
}) {
  const width = max ? Math.max((value / max) * 100, value ? 2 : 0) : 0
  const Tag = onClick ? "button" : "div"
  return (
    <Tag
      type={onClick ? "button" : undefined}
      onClick={onClick}
      title={`${label}: ${value}`}
      className={cn(
        "grid w-full grid-cols-[140px_1fr_32px] items-center gap-3 rounded px-2 py-1.5 text-left text-sm",
        onClick && "hover:bg-secondary/60",
        active && "bg-primary/5 ring-1 ring-primary/30",
      )}
    >
      <span className="truncate text-muted-foreground">{label}</span>
      <span className="h-2.5 rounded-r bg-secondary/60">
        <span className="block h-full rounded-r bg-primary" style={{ width: `${width}%` }} />
      </span>
      <span className="text-right font-semibold tabular-nums">{value}</span>
    </Tag>
  )
}

function Stages({ d }: { d: Dashboard }) {
  const [picked, setPicked] = useState<DashboardPhase | null>(null)
  const max = Math.max(...PHASES.map((p) => d.phases[p]))
  const cases = picked && picked !== "closed" ? d.open.filter((c) => c.phase === picked) : []
  return (
    <Card title="Cases by stage" hint={`${d.open_cases} open · ${d.closed_30d} closed in the last 30 days. Click a stage to see its cases.`}>
      <div className="space-y-0.5">
        {PHASES.map((p) => (
          <BarRow
            key={p}
            label={PHASE_LABEL(p)}
            value={d.phases[p]}
            max={max}
            active={picked === p}
            onClick={() => setPicked(picked === p ? null : p)}
          />
        ))}
      </div>
      {picked === "closed" && (
        <p className="mt-3 border-t pt-3 text-sm">
          <Link to="/pod/cases?status=closed" className="text-primary hover:underline">
            See closed cases →
          </Link>
        </p>
      )}
      {picked && picked !== "closed" && (
        <ul className="mt-3 divide-y border-t">
          {cases.length === 0 && <li className="py-3 text-sm text-muted-foreground">No case is here now.</li>}
          {cases.map((c) => (
            <li key={c.id} className="flex items-center gap-2 py-2 text-sm">
              <Link to={`/pod/cases/${c.id}`} className="font-semibold text-primary hover:underline">
                {c.reference}
              </Link>
              <span className="min-w-0 flex-1 truncate">{c.title}</span>
              <span className="text-xs text-muted-foreground">
                {WORKFLOW_SHORT[c.workflow]} · {c.days_open} d open
              </span>
            </li>
          ))}
        </ul>
      )}
    </Card>
  )
}

function PromiseList({ items, empty }: { items: PromiseItem[]; empty: string }) {
  if (!items.length) return <p className="py-2 text-sm text-muted-foreground">{empty}</p>
  return (
    <ul className="divide-y">
      {items.map((p) => (
        <li key={`${p.case_id}-${p.invoice_number}-${p.expected_date}`} className="flex items-center gap-2 py-2 text-sm">
          <Link to={`/pod/cases/${p.case_id}`} className="font-semibold text-primary hover:underline">
            {p.case_reference}
          </Link>
          <span className="min-w-0 flex-1 truncate">
            {p.case_title} · {p.invoice_number}
          </span>
          <span className="font-semibold tabular-nums">{fmt(p.amount, p.currency)}</span>
          <span className="w-24 text-right text-xs text-muted-foreground">{p.expected_date}</span>
        </li>
      ))}
    </ul>
  )
}

function Promises({ d }: { d: Dashboard }) {
  return (
    <Card title="Payment promises" hint="Approved commitments from customers. A promise is not a receipt: check QuickBooks once it's due.">
      <p className="mb-1 text-xs font-semibold text-brand-navy uppercase">Due in the next 7 days</p>
      <PromiseList items={d.due_this_week} empty="Nothing due this week." />
      <p className="mt-4 mb-1 flex items-center gap-1 text-xs font-semibold text-red-800 uppercase">
        <CircleAlert className="size-3.5" aria-hidden /> Date passed
      </p>
      <PromiseList items={d.overdue_promises} empty="No promise is past its date." />
    </Card>
  )
}

function EmailHealth({ d }: { d: Dashboard }) {
  const e = d.email
  const ok = e.ready && !e.simulated
  return (
    <Card title="Email">
      <p className="flex items-center gap-2 text-sm">
        {ok ? (
          <CircleCheck className="size-4 text-emerald-700" aria-hidden />
        ) : (
          <CircleAlert className="size-4 text-amber-700" aria-hidden />
        )}
        <span className="font-medium">
          {e.simulated ? "Simulated: nothing is really sent" : e.ready ? `Sending through ${PROVIDER[e.provider] ?? e.provider}` : "Can't send yet"}
        </span>
      </p>
      {e.problem && <p className="mt-1 text-xs text-amber-800">{e.problem}</p>}
      <p className="mt-1 flex items-center gap-2 text-xs text-muted-foreground">
        <Mail className="size-3.5" aria-hidden />
        {e.reads_mailbox
          ? `Replies are read from the mailbox every ${e.poll_seconds}s`
          : "Replies are imported by hand (the mailbox isn't read)"}
      </p>
      <dl className="mt-4 grid grid-cols-3 gap-3 border-t pt-3 text-center">
        <div>
          <dt className="text-xs text-muted-foreground">Sent (30 d)</dt>
          <dd className="text-lg font-bold tabular-nums">{e.sent_30d}</dd>
        </div>
        <div>
          <dt className="text-xs text-muted-foreground">Replies (30 d)</dt>
          <dd className="text-lg font-bold tabular-nums">{e.replies_30d}</dd>
        </div>
        <div>
          <dt className="text-xs text-muted-foreground">Avg reply</dt>
          <dd className="text-lg font-bold tabular-nums">{e.avg_reply_hours === null ? "-" : `${e.avg_reply_hours} h`}</dd>
        </div>
      </dl>
      <p className="mt-2 text-xs text-muted-foreground">Last reply: {formatDateTime(e.last_reply_at)}</p>
    </Card>
  )
}

function NeedsYou() {
  const q = useMyQueue()
  const items = [
    ...q.signoffs.map((c) => ({ key: c.id, to: `/pod/cases/${c.id}`, tag: "Sign-off", ref: c.reference, text: c.title })),
    ...q.reviews.map((r) => ({
      key: r.task.id,
      to: `/pod/cases/${r.case_id}`,
      tag: `Review · ${REVIEW_KIND[r.task.kind]}`,
      ref: r.case_reference,
      text: r.task.subject ?? r.task.detail,
    })),
    ...q.emails.map((m) => ({ key: m.id, to: `/pod/cases/${m.case_id}`, tag: "Email", ref: m.case_reference, text: m.subject })),
    ...q.postings.map((t) => ({ key: t.id, to: `/pod/cases/${t.case_id}`, tag: "QuickBooks", ref: t.case_reference, text: t.reference })),
  ]
  return (
    <Card
      title="Needs you now"
      actions={
        q.count > 5 ? (
          <Link to="/pod/queue" className="text-xs text-primary hover:underline">
            All {q.count} →
          </Link>
        ) : undefined
      }
    >
      {q.isPending && <Loading what="your queue" />}
      {!q.isPending && items.length === 0 && <Empty>Nothing is waiting on you.</Empty>}
      <ul className="divide-y">
        {items.slice(0, 5).map((i) => (
          <li key={i.key}>
            <Link to={i.to} className="group flex items-center gap-2 py-2 text-sm">
              <Pill label={i.tag} tone="warn" />
              <span className="font-semibold">{i.ref}</span>
              <span className="min-w-0 flex-1 truncate text-muted-foreground">{i.text}</span>
              <ArrowRight className="size-4 text-muted-foreground transition-transform group-hover:translate-x-0.5" aria-hidden />
            </Link>
          </li>
        ))}
      </ul>
    </Card>
  )
}

function Aging({ d }: { d: Dashboard }) {
  const max = Math.max(...d.aging.map((b) => b.count))
  const oldest = d.open.slice(0, 3)
  return (
    <Card title="Open case age" hint="Days since each open case was started.">
      <div className="space-y-0.5">
        {d.aging.map((b) => (
          <BarRow key={b.label} label={b.label} value={b.count} max={max} />
        ))}
      </div>
      {oldest.length > 0 && (
        <>
          <p className="mt-4 mb-1 text-xs font-semibold text-brand-navy uppercase">Oldest open</p>
          <ul className="divide-y">
            {oldest.map((c) => (
              <li key={c.id} className="flex items-center gap-2 py-2 text-sm">
                <Link to={`/pod/cases/${c.id}`} className="font-semibold text-primary hover:underline">
                  {c.reference}
                </Link>
                <span className="min-w-0 flex-1 truncate">{c.title}</span>
                <Pill label={CASE_PHASE[c.phase === "closed" ? "completed" : c.phase][0]} tone={CASE_PHASE[c.phase === "closed" ? "completed" : c.phase][1]} />
                <span className="w-14 text-right text-xs text-muted-foreground">{c.days_open} d</span>
              </li>
            ))}
          </ul>
        </>
      )}
    </Card>
  )
}

/** The Service POD at a glance: money at stake, where the cases stand, what needs you. */
export function DashboardPage() {
  const { data: d, isPending, isError } = useDashboard()
  const q = useMyQueue()
  const promised = d?.promised.length ? d.promised.map((t) => fmt(t.amount, t.currency)).join(" + ") : "None yet"

  return (
    <AppPage title="Service POD" subtitle="Governed finance workflows on read-only QuickBooks data. You post in QuickBooks by hand.">
      <PodTabs />
      <div className="space-y-6">
        <section aria-label="Workflows">
          <WorkflowCards />
        </section>

        <div className="grid gap-4 sm:grid-cols-3">
          <Tile label="Promised by customers" value={promised} hint="Approved payment commitments" />
          <Tile label="Waiting on you" value={String(q.count)} hint={`${q.reviews.length} review task${q.reviews.length === 1 ? "" : "s"}`} to="/pod/queue" />
          <Tile
            label="Open cases"
            value={d ? String(d.open_cases) : "-"}
            hint={d ? `${d.closed_30d} closed in the last 30 days` : undefined}
            to="/pod/cases"
          />
        </div>

        {isPending && <Loading what="the dashboard" />}
        {isError && <LoadError what="the dashboard" />}
        {d && (
          <div className="grid items-start gap-6 xl:grid-cols-2">
            <Stages d={d} />
            <NeedsYou />
            <Promises d={d} />
            <div className="space-y-6">
              <EmailHealth d={d} />
              <Aging d={d} />
            </div>
          </div>
        )}
      </div>
    </AppPage>
  )
}
