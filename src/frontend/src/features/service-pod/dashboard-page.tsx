import { useState } from "react"
import { Link } from "react-router"
import { ArrowRight, Bot, CircleAlert, CircleCheck, FileText, Inbox, Mail, Sparkles, UserRound } from "lucide-react"

import { cn } from "@/lib/utils"

import type { AiKind, Dashboard, DashboardPhase, PromiseItem } from "./api"
import { useCurrentUser } from "@/features/auth/hooks"

import { AiBadge, AiCard, Card, LivePulse, LoadError, Loading, Pill, PodTabs } from "./components/bits"
import { fmt } from "./flows/shared"
import { useDashboard, useMyQueue } from "./hooks"
import { CASE_PHASE, formatDateTime, REVIEW_KIND, WORKFLOW_SHORT } from "./labels"
import { WorkflowCards } from "./workflows-page"
import { PodPage } from "./components/pod-page"

const PROVIDER: Record<string, string> = { microsoft: "Microsoft 365", brevo: "Brevo", outbox: "the outbox" }

const PHASES: DashboardPhase[] = ["compose", "waiting", "analysis", "review", "ready", "approved", "closed"]

const AI_KIND: Record<AiKind, { label: string; icon: typeof Bot }> = {
  reply_imported: { label: "replies picked up from the mailbox", icon: Inbox },
  reply_read: { label: "replies read and checked", icon: Bot },
  reply_not_read: { label: "replies handed to a person", icon: UserRound },
  commentary: { label: "cited commentaries drafted", icon: FileText },
}

function greeting(): string {
  const h = new Date().getHours()
  return h < 12 ? "Good morning" : h < 17 ? "Good afternoon" : "Good evening"
}

/** Who you are, what waits on you, and what the AI did while you were away. */
function Hero({ d, waiting }: { d: Dashboard | undefined; waiting: number }) {
  const { data: me } = useCurrentUser()
  const done = d ? Object.values(d.ai_activity.last_7_days).reduce((a, b) => a + b, 0) : 0
  return (
    <section
      aria-label="Today"
      className="relative overflow-hidden rounded-2xl border border-ai-border bg-gradient-to-r from-brand-navy via-[#1d2f63] to-[#3b2a8c] p-5 text-white shadow-[0_18px_40px_-24px_rgb(59_42_140/0.7)]"
    >
      <div aria-hidden className="pointer-events-none absolute -top-16 right-10 size-56 rounded-full bg-violet-400/20 blur-3xl" />
      <div className="relative flex flex-wrap items-end justify-between gap-4">
        <div>
          <p className="flex items-center gap-2 text-xs font-medium text-violet-200">
            <Sparkles className="size-3.5" aria-hidden /> Finance AI · Service POD
          </p>
          <h2 className="mt-1 text-xl font-semibold tracking-tight sm:text-2xl">
            {greeting()}
            {me ? `, ${me.full_name}` : ""}
          </h2>
          <p className="mt-1 text-sm text-slate-200">
            <Link to="/pod/queue" className="font-semibold text-white underline-offset-4 hover:underline">
              {waiting} item{waiting === 1 ? "" : "s"} need{waiting === 1 ? "s" : ""} you
            </Link>{" "}
            · the AI handled {done} thing{done === 1 ? "" : "s"} in the last 7 days · QuickBooks stays read-only
          </p>
        </div>
        {d && (
          <ul className="flex flex-wrap gap-2 text-xs">
            {(Object.keys(AI_KIND) as AiKind[]).map((k) => {
              const Icon = AI_KIND[k].icon
              return (
                <li key={k} className="flex items-center gap-1.5 rounded-lg bg-white/10 px-2.5 py-1.5 ring-1 ring-white/15 backdrop-blur" title={AI_KIND[k].label}>
                  <Icon className="size-3.5 text-violet-200" aria-hidden />
                  <span className="font-semibold tabular-nums">{d.ai_activity.last_7_days[k]}</span>
                  <span className="text-slate-200">{AI_KIND[k].label}</span>
                </li>
              )
            })}
          </ul>
        )}
      </div>
    </section>
  )
}

function ago(iso: string): string {
  const mins = Math.max(0, Math.round((Date.now() - new Date(iso).getTime()) / 60_000))
  if (mins < 60) return `${mins} min ago`
  const hours = Math.round(mins / 60)
  return hours < 24 ? `${hours} h ago` : `${Math.round(hours / 24)} d ago`
}

/** The automation's latest work, from the audit trail. */
function AiActivityFeed({ d }: { d: Dashboard }) {
  const items = d.ai_activity.recent
  return (
    <AiCard title="AI activity" hint="What the automation did lately, as the audit trail records it. People still approve every step." badge={<AiBadge label="Live" />}>
      {items.length === 0 ? (
        <p className="py-4 text-center text-sm text-muted-foreground">Nothing yet: the AI acts when replies arrive or commentary is drafted.</p>
      ) : (
        <ul className="space-y-2.5">
          {items.map((e) => {
            const Icon = AI_KIND[e.kind].icon
            return (
              <li key={`${e.at}-${e.summary}`} className="flex gap-2.5 text-sm">
                <span className="mt-0.5 flex size-6 shrink-0 items-center justify-center rounded-full bg-ai-soft text-ai ring-1 ring-ai-border">
                  <Icon className="size-3.5" aria-hidden />
                </span>
                <span className="min-w-0 flex-1">
                  <span className="line-clamp-2">{e.summary}</span>
                  <span className="text-xs text-muted-foreground">{ago(e.at)}</span>
                </span>
              </li>
            )
          })}
        </ul>
      )}
    </AiCard>
  )
}

/** The latest Treasury forecast's base cash, week by week, against the buffer. */
function CashRunway({ d }: { d: Dashboard }) {
  const cash = d.cash
  if (!cash) {
    return (
      <Card title="Cash runway" hint="From the latest Treasury forecast.">
        <p className="py-4 text-center text-sm text-muted-foreground">
          No forecast yet.{" "}
          <Link to="/pod/treasury" className="text-primary hover:underline">
            Start a 13-week forecast
          </Link>
        </p>
      </Card>
    )
  }
  const points = [Number(cash.opening), ...cash.weeks.map((w) => Number(w.ending_cash))]
  const buffer = Number(cash.buffer)
  const hi = Math.max(...points, buffer) * 1.1
  const lo = Math.min(0, ...points)
  const W = 320
  const H = 90
  const x = (i: number) => (i * W) / (points.length - 1)
  const y = (v: number) => H - ((v - lo) / (hi - lo || 1)) * H
  return (
    <Card
      title="Cash runway"
      hint={`Base scenario of ${cash.case_reference}, 13 weeks`}
      actions={
        <Link to={`/pod/cases/${cash.case_id}`} className="text-xs text-primary hover:underline">
          Open forecast →
        </Link>
      }
    >
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <p className="text-xs text-muted-foreground">Ending cash</p>
          <p className="text-2xl font-bold tracking-tight text-brand-navy tabular-nums">{fmt(cash.ending_cash, cash.currency)}</p>
          <p className={cn("mt-0.5 text-xs font-medium", cash.first_breach ? "text-red-700" : "text-emerald-700")}>
            {cash.first_breach ? `Below the ${fmt(cash.buffer, cash.currency)} buffer from ${cash.first_breach}` : "Above the buffer for 13 weeks"}
          </p>
        </div>
        <svg viewBox={`0 0 ${W} ${H}`} className="h-20 w-full max-w-xs" role="img" aria-label="Weekly ending cash against the buffer">
          <line x1="0" x2={W} y1={y(buffer)} y2={y(buffer)} strokeDasharray="4 4" className="stroke-muted-foreground" strokeWidth="1.2" />
          <polyline fill="none" strokeWidth="2" strokeLinejoin="round" className="stroke-[#2a78d6]" points={points.map((v, i) => `${x(i)},${y(v)}`).join(" ")} />
          {points.map((v, i) => (
            <circle key={i} cx={x(i)} cy={y(v)} r="2.5" className={v < buffer ? "fill-red-600" : "fill-[#2a78d6]"}>
              <title>{i === 0 ? `Opening ${fmt(String(v), cash.currency)}` : `Week ${i}: ${fmt(String(v), cash.currency)}`}</title>
            </circle>
          ))}
        </svg>
      </div>
    </Card>
  )
}
const PHASE_LABEL = (p: DashboardPhase) => (p === "closed" ? "Closed (30 days)" : CASE_PHASE[p][0])

function DashboardKpis({
  openCases,
  waitingCount,
  promised,
}: {
  openCases: number
  waitingCount: number
  promised: string
}) {
  return (
    <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
      <Link
        to="/pod/queue"
        className="group flex flex-col justify-between rounded-xl border border-border/80 bg-card p-4 shadow-2xs transition-all duration-200 hover:-translate-y-0.5 hover:border-amber-400/80 hover:shadow-md"
      >
        <div className="flex items-start justify-between">
          <div>
            <span className="text-[11px] font-bold uppercase tracking-wider text-muted-foreground">Needs You Now</span>
            <p className="mt-1 text-2xl font-bold tracking-tight text-amber-600 dark:text-amber-400 tabular-nums">
              {waitingCount}
            </p>
          </div>
          <span className="rounded-md bg-amber-50 px-2 py-0.5 text-[10px] font-semibold text-amber-800 dark:bg-amber-950/50 dark:text-amber-300">
            Action
          </span>
        </div>
        <span className="mt-3 flex items-center gap-1 text-xs font-medium text-amber-700 dark:text-amber-300 group-hover:underline">
          Go to queue <ArrowRight className="size-3 transition-transform group-hover:translate-x-0.5" />
        </span>
      </Link>

      <Link
        to="/pod/cases"
        className="group flex flex-col justify-between rounded-xl border border-border/80 bg-card p-4 shadow-2xs transition-all duration-200 hover:-translate-y-0.5 hover:border-primary/80 hover:shadow-md"
      >
        <div className="flex items-start justify-between">
          <div>
            <span className="text-[11px] font-bold uppercase tracking-wider text-muted-foreground">Open Cases</span>
            <p className="mt-1 text-2xl font-bold tracking-tight text-foreground tabular-nums">
              {openCases}
            </p>
          </div>
          <span className="rounded-md bg-sky-50 px-2 py-0.5 text-[10px] font-semibold text-sky-800 dark:bg-sky-950/50 dark:text-sky-300">
            Categorized
          </span>
        </div>
        <span className="mt-3 flex items-center gap-1 text-xs font-medium text-primary group-hover:underline">
          View all cases <ArrowRight className="size-3 transition-transform group-hover:translate-x-0.5" />
        </span>
      </Link>

      <div className="flex flex-col justify-between rounded-xl border border-border/80 bg-card p-4 shadow-2xs transition-all duration-200 hover:shadow-xs">
        <div className="flex items-start justify-between">
          <div>
            <span className="text-[11px] font-bold uppercase tracking-wider text-muted-foreground">Payment Promises</span>
            <p className="mt-1 text-xl font-bold tracking-tight text-emerald-600 dark:text-emerald-400 tabular-nums truncate" title={promised}>
              {promised}
            </p>
          </div>
          <span className="rounded-md bg-emerald-50 px-2 py-0.5 text-[10px] font-semibold text-emerald-800 dark:bg-emerald-950/50 dark:text-emerald-300">
            Commitments
          </span>
        </div>
        <span className="mt-3 text-xs text-muted-foreground">Approved customer promises</span>
      </div>

      <div className="flex flex-col justify-between rounded-xl border border-border/80 bg-card p-4 shadow-2xs transition-all duration-200 hover:shadow-xs">
        <div className="flex items-start justify-between">
          <div>
            <span className="text-[11px] font-bold uppercase tracking-wider text-muted-foreground">QuickBooks Status</span>
            <div className="mt-1.5 flex items-center gap-2">
              <LivePulse color="emerald" />
              <span className="text-sm font-bold text-foreground">Read-Only Live</span>
            </div>
          </div>
          <span className="rounded-md bg-emerald-50 px-2 py-0.5 text-[10px] font-semibold text-emerald-800 dark:bg-emerald-950/50 dark:text-emerald-300">
            Governed
          </span>
        </div>
        <span className="mt-3 text-xs text-muted-foreground">5 Autonomous Workflows Active</span>
      </div>
    </div>
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
    ...q.signoffs.map((c) => ({ key: c.id, to: `/pod/cases/${c.id}`, tag: "Sign-off", tone: "good" as const, ref: c.reference, text: c.title })),
    ...q.reviews.map((r) => ({
      key: r.task.id,
      to: `/pod/cases/${r.case_id}`,
      tag: `Review · ${REVIEW_KIND[r.task.kind]}`,
      tone: "warn" as const,
      ref: r.case_reference,
      text: r.task.subject ?? r.task.detail,
    })),
    ...q.emails.map((m) => ({ key: m.id, to: `/pod/cases/${m.case_id}`, tag: "Email Draft", tone: "ai" as const, ref: m.case_reference, text: m.subject })),
    ...q.postings.map((t) => ({ key: t.id, to: `/pod/cases/${t.case_id}`, tag: "QuickBooks", tone: "info" as const, ref: t.case_reference, text: t.reference })),
  ]
  return (
    <Card
      title="Human-in-the-Loop: Needs You Now"
      hint="Authorized human sign-offs, email draft checks, and posting confirmations"
      actions={
        q.count > 5 ? (
          <Link to="/pod/queue" className="text-xs font-semibold text-primary hover:underline flex items-center gap-1">
            All {q.count} in queue →
          </Link>
        ) : undefined
      }
    >
      {q.isPending && <Loading what="your queue" />}
      {!q.isPending && items.length === 0 && (
        <div className="py-6 text-center text-xs text-muted-foreground">
          <p className="font-semibold text-emerald-600 dark:text-emerald-400">All caught up! ✨</p>
          <p className="mt-0.5">No tasks currently require human sign-off.</p>
        </div>
      )}
      <ul className="divide-y">
        {items.slice(0, 5).map((i) => (
          <li key={i.key}>
            <Link to={i.to} className="group flex items-center gap-2.5 py-2.5 text-sm transition-colors hover:bg-muted/40 rounded px-1.5">
              <Pill label={i.tag} tone={i.tone} />
              <span className="font-semibold text-brand-navy">{i.ref}</span>
              <span className="min-w-0 flex-1 truncate text-xs text-muted-foreground group-hover:text-foreground">{i.text}</span>
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
    <PodPage
      title="Finance Service POD"
      subtitle="Governed finance workflows on read-only QuickBooks books. Real-time monitoring, customer dunning, and audit-ready reconciliations."
    >
      <PodTabs />
      <div className="space-y-6">
        <Hero d={d} waiting={q.count} />

        <DashboardKpis
          openCases={d?.open_cases ?? 0}
          waitingCount={q.count}
          promised={promised}
        />

        <section aria-label="Workflows" className="space-y-2.5">
          <div className="flex items-center justify-between">
            <h2 className="text-xs font-bold uppercase tracking-wider text-muted-foreground">
              Workflows
            </h2>
            <span className="text-xs text-muted-foreground">5 active workflows</span>
          </div>
          <WorkflowCards />
        </section>

        {isPending && <Loading what="the dashboard" />}
        {isError && <LoadError what="the dashboard" />}
        {d && (
          <div className="grid items-start gap-6 xl:grid-cols-2">
            <NeedsYou />
            <AiActivityFeed d={d} />
            <CashRunway d={d} />
            <Stages d={d} />
            <Promises d={d} />
            <div className="space-y-6">
              <EmailHealth d={d} />
              <Aging d={d} />
            </div>
          </div>
        )}
      </div>
    </PodPage>
  )
}
