import { useState } from "react"
import { Link } from "react-router"
import { ArrowRight, Bot, CircleCheck, Database, FileCheck, Plus, Sparkles, Upload } from "lucide-react"

import { Button } from "@/components/ui/button"
import { useCurrentUser } from "@/features/auth/hooks"
import { AiBadge, AiCard, Card, Empty, LoadError, Loading } from "@/features/service-pod/components/bits"
import { cn } from "@/lib/utils"

import type { AiKind, FinanceDashboard, WorkflowTile } from "./api"
import { useFinanceDashboard, useFinanceMe } from "./hooks"
import { formatMeasure, WORKFLOW_SHORT } from "./labels"
import { FinancePage } from "./components/finance-page"
import { NewCase } from "./components/new-case"
import { QueueRow } from "./components/queue-list"

const AI_KIND: Record<AiKind, { label: string; icon: typeof Bot }> = {
  agent_step: { label: "steps done by the agents", icon: Bot },
  posted: { label: "documents posted to ERPNext", icon: Upload },
  verified: { label: "postings verified", icon: FileCheck },
}

function greeting(): string {
  const h = new Date().getHours()
  return h < 12 ? "Good morning" : h < 17 ? "Good afternoon" : "Good evening"
}

function ago(iso: string): string {
  const mins = Math.max(0, Math.round((Date.now() - new Date(iso).getTime()) / 60_000))
  if (mins < 60) return `${mins} min ago`
  const hours = Math.round(mins / 60)
  return hours < 24 ? `${hours} h ago` : `${Math.round(hours / 24)} d ago`
}

function money(value: string, currency: string | null): string {
  return `${currency ?? ""} ${Number(value).toLocaleString(undefined, { maximumFractionDigits: 0 })}`.trim()
}

/** Who you are, what waits on you, what the agents did, and where the data comes from. */
function Hero({ d, onNew }: { d: FinanceDashboard; onNew: () => void }) {
  const { data: me } = useCurrentUser()
  const { data: finance } = useFinanceMe()
  const canOpen = Boolean(finance?.is_admin || finance?.can_open.length)
  const waiting = d.my_queue.length
  const ai = d.ai?.last_7_days
  const done = ai ? Object.values(ai).reduce((a, b) => a + b, 0) : 0
  const source = d.kpis?.source_name
  return (
    <section
      aria-label="Today"
      className="relative overflow-hidden rounded-2xl border border-ai-border bg-gradient-to-r from-brand-navy via-[#1d2f63] to-[#3b2a8c] p-5 text-white shadow-[0_18px_40px_-24px_rgb(59_42_140/0.7)]"
    >
      <div aria-hidden className="pointer-events-none absolute -top-16 right-10 size-56 rounded-full bg-violet-400/20 blur-3xl" />
      <div className="relative flex flex-wrap items-end justify-between gap-4">
        <div className="min-w-0">
          <p className="flex items-center gap-2 text-xs font-medium text-violet-200">
            <Sparkles className="size-3.5" aria-hidden /> Finance AI · Finance POD
          </p>
          <h2 className="mt-1 text-xl font-semibold tracking-tight sm:text-2xl">
            {greeting()}
            {me ? `, ${me.full_name}` : ""}
          </h2>
          <p className="mt-1 text-sm text-slate-200">
            <Link to="/finance/queue" className="font-semibold text-white underline-offset-4 hover:underline">
              {waiting} item{waiting === 1 ? "" : "s"} need{waiting === 1 ? "s" : ""} you
            </Link>{" "}
            · the agents handled {done} thing{done === 1 ? "" : "s"} in the last 7 days
            {source ? ` · ${source} stays the books` : ""}
          </p>
          {ai && (
            <ul className="mt-3 flex flex-wrap gap-2 text-xs">
              {(Object.keys(AI_KIND) as AiKind[]).map((k) => {
                const Icon = AI_KIND[k].icon
                return (
                  <li key={k} className="flex items-center gap-1.5 rounded-lg bg-white/10 px-2.5 py-1.5 ring-1 ring-white/15">
                    <Icon className="size-3.5 text-violet-200" aria-hidden />
                    <span className="font-semibold tabular-nums">{ai[k]}</span>
                    <span className="text-slate-200">{AI_KIND[k].label}</span>
                  </li>
                )
              })}
            </ul>
          )}
        </div>
        {canOpen && (
          <Button onClick={onNew} className="bg-white text-brand-navy hover:bg-violet-50">
            <Plus className="size-4" aria-hidden /> New case
          </Button>
        )}
      </div>
    </section>
  )
}

function Tile({ to, label, value, hint, tone }: { to: string; label: string; value: string; hint: string; tone: string }) {
  return (
    <Link
      to={to}
      className="group flex flex-col justify-between rounded-xl border border-border/80 bg-card p-4 shadow-2xs transition-all duration-200 hover:-translate-y-0.5 hover:shadow-md"
    >
      <span className="text-[11px] font-bold uppercase tracking-wider text-muted-foreground">{label}</span>
      <span className={cn("mt-1 text-2xl font-bold tracking-tight tabular-nums", tone)}>{value}</span>
      <span className="mt-2 flex items-center gap-1 text-xs text-muted-foreground group-hover:text-primary">
        {hint} <ArrowRight className="size-3 transition-transform group-hover:translate-x-0.5" aria-hidden />
      </span>
    </Link>
  )
}

function Kpis({ d }: { d: FinanceDashboard }) {
  const k = d.kpis
  if (!k) return null
  const snapshot = k.last_snapshot_at ? new Date(k.last_snapshot_at).toLocaleString() : "none yet"
  return (
    <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-4">
      <Tile to="/finance/queue" label="Needs you now" value={String(d.my_queue.length)} hint="Go to My Queue" tone="text-amber-600" />
      <Tile to="/finance/cases" label="Open cases" value={String(k.open_ap + k.open_ar)} hint={`AP ${k.open_ap} · AR ${k.open_ar}`} tone="text-brand-navy" />
      <Tile to="/finance/queue" label="Waiting in ERPNext" value={String(k.erp_pending)} hint="to post or verify" tone="text-teal-700" />
      {k.overdue_receivables !== null ? (
        <Tile
          to="/finance/cases?workflow=ar_billing"
          label="Overdue receivables"
          value={money(k.overdue_receivables, k.currency)}
          hint={`${k.overdue_clients} client${k.overdue_clients === 1 ? "" : "s"} overdue`}
          tone="text-red-700"
        />
      ) : (
        <Tile to="/finance/setup" label="Source data" value={k.source_name ?? "Not connected"} hint={`Last snapshot ${snapshot}`} tone="text-brand-navy text-lg" />
      )}
    </div>
  )
}

/** A workflow at a glance: what it does, how many are open, and its measures. */
function WorkflowCard({ w }: { w: WorkflowTile }) {
  return (
    <Link
      to={`/finance/cases?workflow=${w.key}`}
      title={w.description}
      className="group flex flex-col rounded-xl border border-border/80 bg-card p-4 shadow-2xs transition-all hover:-translate-y-0.5 hover:border-primary/40 hover:shadow-md"
    >
      <div className="flex items-start justify-between gap-2">
        <h3 className="text-sm font-semibold">{w.name}</h3>
        <span className="rounded bg-muted px-1.5 py-0.5 font-mono text-[10px] text-muted-foreground">{w.prefix}</span>
      </div>
      <p className="mt-0.5 text-xs text-muted-foreground">{WORKFLOW_SHORT[w.key] ?? w.description}</p>
      <div className="mt-3 flex items-baseline gap-4 text-xs">
        <span><span className="text-lg font-semibold tabular-nums">{w.open}</span> <span className="text-muted-foreground">open</span></span>
        <span><span className="text-lg font-semibold tabular-nums">{w.completed_30d}</span> <span className="text-muted-foreground">done in 30 days</span></span>
      </div>
      {w.measures.length > 0 && (
        <ul className="mt-2 space-y-0.5 border-t border-border/60 pt-2 text-xs">
          {w.measures.slice(0, 3).map((m) => (
            <li key={m.id} className="flex justify-between gap-2">
              <span className="text-muted-foreground">{m.label}</span>
              <span className="font-medium tabular-nums">{formatMeasure(m.value, m.unit)}</span>
            </li>
          ))}
        </ul>
      )}
      <span className="mt-auto pt-3 text-xs font-medium text-primary opacity-80 group-hover:opacity-100">Open cases →</span>
    </Link>
  )
}

function Area({ title, hint, tiles }: { title: string; hint: string; tiles: WorkflowTile[] }) {
  if (tiles.length === 0) return null
  return (
    <section className="space-y-2">
      <div className="flex items-baseline justify-between gap-2">
        <h2 className="text-xs font-bold uppercase tracking-wider text-muted-foreground">{title}</h2>
        <span className="text-xs text-muted-foreground">{hint}</span>
      </div>
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 xl:grid-cols-4">
        {tiles.map((w) => <WorkflowCard key={w.key} w={w} />)}
      </div>
    </section>
  )
}

function AiActivity({ d }: { d: FinanceDashboard }) {
  const items = d.ai?.recent ?? []
  return (
    <AiCard title="AI activity" hint="What the agents and the app did lately, from the audit trail. People still decide every step." badge={<AiBadge label="Live" />}>
      {items.length === 0 ? (
        <p className="py-4 text-center text-sm text-muted-foreground">Nothing in the last 7 days.</p>
      ) : (
        <ul className="space-y-2.5">
          {items.map((e) => {
            const Icon = AI_KIND[e.kind].icon
            // "PRQ-0057: Step 1.2.1 Budget agent checks: run by the agent" -> "Budget agent checks"
            const text = (e.reference && e.summary.startsWith(`${e.reference}: `) ? e.summary.slice(e.reference.length + 2) : e.summary)
              .replace(/^Step [\w.]+ /, "")
              .replace(/: run by the agent/, "")
            return (
              <li key={`${e.at}-${e.summary}`} className="flex gap-2.5 text-sm">
                <span className="mt-0.5 flex size-6 shrink-0 items-center justify-center rounded-full bg-ai-soft text-ai ring-1 ring-ai-border">
                  <Icon className="size-3.5" aria-hidden />
                </span>
                <span className="min-w-0 flex-1">
                  {e.case_id && e.reference ? (
                    <Link to={`/finance/cases/${e.case_id}`} className="font-medium text-primary hover:underline">{e.reference}</Link>
                  ) : null}{" "}
                  <span className="line-clamp-2 inline">{text}</span>
                  <span className="block text-xs text-muted-foreground">{ago(e.at)}</span>
                </span>
              </li>
            )
          })}
        </ul>
      )}
    </AiCard>
  )
}

export function FinanceDashboardPage() {
  const { data, isLoading, isError } = useFinanceDashboard()
  const [creating, setCreating] = useState(false)
  const ap = data?.workflows.filter((w) => w.area === "AP") ?? []
  const ar = data?.workflows.filter((w) => w.area === "AR") ?? []

  return (
    <FinancePage
      title="Finance POD"
      subtitle="Accounts Payable and Receivable agents: each step as the requirement draws it, an agent prepares and a person decides."
    >
      {isLoading && <Loading what="the Finance POD" />}
      {isError && <LoadError what="the Finance POD" />}
      {data && (
        <div className="space-y-5">
          <Hero d={data} onNew={() => setCreating(true)} />
          {creating && <NewCase onClose={() => setCreating(false)} />}
          <Kpis d={data} />

          {data.workflows.length === 0 ? (
            <Card title="Workflows">
              <Empty icon={<Database className="size-5" />}>No Finance POD workflow is yours yet: ask a Finance Admin for a capacity.</Empty>
            </Card>
          ) : (
            <>
              <Area title="Accounts Payable" hint="Procure-to-Pay" tiles={ap} />
              <Area title="Accounts Receivable" hint="Order-to-Cash" tiles={ar} />
            </>
          )}

          <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
            <Card
              title="Needs you now"
              hint="Decisions first, then reviews, mail, postings."
              actions={
                data.my_queue.length > 0 && (
                  <Link to="/finance/queue" className="flex items-center gap-1 text-sm font-medium text-primary hover:underline">
                    All {data.my_queue.length} <ArrowRight className="size-4" aria-hidden />
                  </Link>
                )
              }
            >
              {data.my_queue.length === 0 ? (
                <Empty icon={<CircleCheck className="size-5" />}>All clear: nothing waits on you.</Empty>
              ) : (
                <ul className="divide-y divide-border/60">
                  {data.my_queue.slice(0, 5).map((item) => (
                    <QueueRow key={`${item.type}-${item.case_id}-${item.step_key}-${item.step_title}`} item={item} />
                  ))}
                </ul>
              )}
            </Card>
            <AiActivity d={data} />
          </div>
        </div>
      )}
    </FinancePage>
  )
}

