import { useState } from "react"
import { Link } from "react-router"
import { ArrowRight, Bot, Search, ShieldCheck, UserRound } from "lucide-react"

import { Input } from "@/components/ui/input"
import { Card, LoadError, Loading } from "@/features/service-pod/components/bits"
import { cn } from "@/lib/utils"

import type { Overview } from "./api"
import { FpodPage } from "./components/fpod-page"
import { useOverview } from "./hooks"
import {
  GUARDRAILS,
  PAYMENTS_FLOW,
  PAYMENTS_GUARDRAILS,
  PHASE_1,
  PHASE_3,
  PHASE_3_GUARDRAILS,
  RECEIVABLES_FLOW,
  RECEIVABLES_GUARDRAILS,
  type ProcessStep,
} from "./labels"
import { AGENTS, AREAS, type AreaKey } from "./registry"

const FLOWS: Record<AreaKey, { steps: ProcessStep[]; guardrails: string[] }> = {
  purchasing: { steps: PHASE_1, guardrails: GUARDRAILS },
  invoices: { steps: PHASE_3, guardrails: PHASE_3_GUARDRAILS },
  payments: { steps: PAYMENTS_FLOW, guardrails: PAYMENTS_GUARDRAILS },
  receivables: { steps: RECEIVABLES_FLOW, guardrails: RECEIVABLES_GUARDRAILS },
}

const READINESS: { key: string; label: string }[] = [
  { key: "cost_centres", label: "Cost centres" },
  { key: "grants", label: "Grants" },
  { key: "budgets", label: "Budgets" },
  { key: "catalogue", label: "Contract prices" },
  { key: "vendors", label: "Vendors" },
  { key: "authority", label: "Authority matrix" },
]

/** Everything that waits on a person, from every area's pages. */
function Waiting({ o }: { o: Overview }) {
  const rows = AREAS.flatMap((a) =>
    a.pages.filter((p) => p.count && p.count(o) > 0).map((p) => ({ area: a.name, page: p, n: p.count!(o) })),
  )
  if (rows.length === 0)
    return (
      <p className="rounded-xl border border-emerald-200 bg-emerald-50 px-4 py-3 text-sm text-emerald-900">
        Nothing is waiting for a person right now: the agents have it.
      </p>
    )
  return (
    <ul className="grid gap-2 sm:grid-cols-2 xl:grid-cols-3">
      {rows.map(({ area, page, n }) => {
        const Icon = page.icon
        return (
          <li key={page.to}>
            <Link to={page.to} className="flex items-center gap-3 rounded-xl border border-amber-200 bg-amber-50/70 px-4 py-3 hover:bg-amber-100/70">
              <Icon className="size-5 text-amber-800" aria-hidden />
              <span className="min-w-0 flex-1">
                <span className="block text-sm font-semibold text-amber-950">
                  {n} · {page.label}
                </span>
                <span className="text-xs text-amber-900/80">{area}</span>
              </span>
              <ArrowRight className="size-4 text-amber-800" aria-hidden />
            </Link>
          </li>
        )
      })}
    </ul>
  )
}

function AreaCards({ o }: { o: Overview }) {
  return (
    <div className="grid gap-4 md:grid-cols-2 2xl:grid-cols-4">
      {AREAS.map((a) => {
        const Icon = a.icon
        const agents = AGENTS.filter((g) => g.area === a.key)
        return (
          <section key={a.key} className="rounded-2xl border border-border/80 bg-card p-4 shadow-[0_1px_3px_rgba(15,33,66,0.04)]">
            <div className="flex items-start gap-3">
              <span className="flex size-10 items-center justify-center rounded-xl bg-primary/10 text-primary">
                <Icon className="size-5" aria-hidden />
              </span>
              <div>
                <h2 className="font-semibold text-brand-navy dark:text-foreground">{a.name}</h2>
                <p className="text-xs text-muted-foreground">{a.tagline}</p>
                <p className="mt-1 flex items-center gap-1 text-xs text-violet-700 dark:text-violet-300">
                  <Bot className="size-3.5" aria-hidden /> {agents.length} agents
                </p>
              </div>
            </div>
            <ul className="mt-3 space-y-1">
              {a.pages.map((p) => {
                const n = p.count ? p.count(o) : 0
                const PIcon = p.icon
                return (
                  <li key={p.to}>
                    <Link to={p.to} className="flex items-center gap-2 rounded-lg px-2 py-1.5 text-sm hover:bg-muted">
                      <PIcon className="size-4 text-muted-foreground" aria-hidden />
                      <span className="flex-1">{p.label}</span>
                      {n > 0 && <span className="rounded-full bg-amber-100 px-1.5 text-[11px] font-semibold text-amber-900">{n}</span>}
                    </Link>
                  </li>
                )
              })}
            </ul>
          </section>
        )
      })}
    </div>
  )
}

/** Every agent in one directory: scales to any number, searchable, filterable by area. */
function AgentDirectory({ o }: { o: Overview }) {
  const [q, setQ] = useState("")
  const [area, setArea] = useState<AreaKey | null>(null)
  const shown = AGENTS.filter(
    (g) => (!area || g.area === area) && (!q.trim() || `${g.name} ${g.does} ${g.people}`.toLowerCase().includes(q.trim().toLowerCase())),
  )
  return (
    <Card
      title={`Agents (${AGENTS.length})`}
      hint="What each agent does and who it works with. Agents prepare; people decide."
      actions={
        <div className="flex flex-wrap items-center gap-2">
          <div className="relative">
            <Search className="absolute top-1/2 left-2.5 size-3.5 -translate-y-1/2 text-muted-foreground" aria-hidden />
            <Input className="h-8 w-48 pl-8 text-xs" placeholder="Find an agent" value={q} onChange={(e) => setQ(e.target.value)} />
          </div>
          {[null, ...AREAS.map((a) => a.key)].map((k) => (
            <button
              key={k ?? "all"}
              type="button"
              onClick={() => setArea(k)}
              className={cn("rounded-full border px-2.5 py-0.5 text-xs", area === k ? "border-primary bg-primary text-primary-foreground" : "border-border hover:bg-muted")}
            >
              {k ? AREAS.find((a) => a.key === k)!.name : "All"}
            </button>
          ))}
        </div>
      }
    >
      <ul className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
        {shown.map((g) => {
          const Icon = g.icon
          const n = g.busy ? g.busy(o) : 0
          return (
            <li key={g.key}>
              <Link to={g.to} className="flex h-full flex-col rounded-xl border border-violet-200/70 bg-gradient-to-b from-violet-50/60 to-transparent p-3 hover:border-violet-300 dark:border-violet-900/50">
                <div className="flex items-center gap-2">
                  <span className="flex size-8 items-center justify-center rounded-lg bg-violet-100 text-violet-700 dark:bg-violet-950">
                    <Icon className="size-4" aria-hidden />
                  </span>
                  <span className="flex-1 font-semibold">{g.name}</span>
                  {n > 0 && <span className="rounded-full bg-amber-100 px-1.5 text-[11px] font-semibold text-amber-900">{n}</span>}
                </div>
                <p className="mt-2 flex-1 text-xs text-muted-foreground">{g.does}</p>
                <p className="mt-2 flex items-center gap-1 text-[11px] text-sky-800 dark:text-sky-300">
                  <UserRound className="size-3" aria-hidden /> {g.people}
                  <span className="ml-auto text-muted-foreground">{AREAS.find((a) => a.key === g.area)!.name}</span>
                </p>
              </Link>
            </li>
          )
        })}
        {shown.length === 0 && <li className="text-sm text-muted-foreground">No agent matches.</li>}
      </ul>
    </Card>
  )
}

function Flow() {
  const [area, setArea] = useState<AreaKey>("purchasing")
  const { steps, guardrails } = FLOWS[area]
  return (
    <Card
      title="How the work flows"
      hint="Violet steps are AI agents, blue are people."
      actions={
        <div className="flex flex-wrap rounded-lg border border-border p-0.5 text-xs">
          {AREAS.map((a) => (
            <button
              key={a.key}
              type="button"
              onClick={() => setArea(a.key)}
              className={cn("rounded-md px-3 py-1 font-medium", area === a.key ? "bg-primary text-primary-foreground" : "text-muted-foreground")}
            >
              {a.name}
            </button>
          ))}
        </div>
      }
    >
      <ol className={cn("grid gap-3 md:grid-cols-2", steps.length >= 5 ? "xl:grid-cols-5" : steps.length === 4 ? "xl:grid-cols-4" : "xl:grid-cols-3")}>
        {steps.map((step, i) => (
          <li key={step.id} className="relative rounded-xl border border-primary/25 bg-gradient-to-b from-primary/5 to-transparent p-3 text-xs">
            <p className="text-sm font-semibold text-brand-navy dark:text-foreground">{step.title}</p>
            <p className="text-muted-foreground">{step.who}</p>
            <ul className="mt-2 space-y-2">
              {step.tasks.map((task) => {
                const TaskIcon = task.actor === "agent" ? Bot : UserRound
                return (
                  <li key={task.id}>
                    <p className="flex items-center gap-1.5 font-medium">
                      <TaskIcon className={cn("size-3.5", task.actor === "agent" ? "text-violet-600" : "text-sky-700")} aria-label={task.actor === "agent" ? "AI agent" : "Person"} />
                      {task.title}
                    </p>
                    <ul className="mt-0.5 list-disc space-y-0.5 pl-5 text-muted-foreground">
                      {task.steps.map((s) => (
                        <li key={s}>{s}</li>
                      ))}
                    </ul>
                  </li>
                )
              })}
            </ul>
            {i < steps.length - 1 && <ArrowRight className="absolute top-1/2 -right-3 z-10 hidden size-4 -translate-y-1/2 text-primary/50 xl:block" aria-hidden />}
          </li>
        ))}
      </ol>
      <ul className="mt-4 grid gap-1.5 text-sm sm:grid-cols-2">
        {guardrails.map((g) => (
          <li key={g} className="flex items-start gap-2">
            <ShieldCheck className="mt-0.5 size-4 shrink-0 text-emerald-600" aria-hidden />
            {g}
          </li>
        ))}
      </ul>
    </Card>
  )
}

function Readiness({ o }: { o: Overview }) {
  const missing = READINESS.filter((r) => !(o.reference[r.key] ?? 0))
  return (
    <p className="text-xs text-muted-foreground">
      Reference data:{" "}
      {missing.length === 0 ? (
        <span className="text-emerald-700">all loaded</span>
      ) : (
        <>
          <span className="text-amber-800">missing {missing.map((m) => m.label.toLowerCase()).join(", ")}</span> ·{" "}
          <Link to="/finance-pod/setup" className="text-primary hover:underline">
            load it in Setup
          </Link>
        </>
      )}
    </p>
  )
}

export function FinancePodHomePage() {
  const overview = useOverview()
  const o = overview.data
  return (
    <FpodPage title="Finance POD" subtitle="Procure-to-pay and client accounts with AI agents and people in the loop.">
      {overview.isPending ? (
        <Loading what="the Finance POD" />
      ) : overview.isError || !o ? (
        <LoadError what="the Finance POD" />
      ) : (
        <div className="space-y-5">
          <section aria-label="Waiting for you" className="space-y-2">
            <h2 className="text-sm font-semibold text-brand-navy dark:text-foreground">Waiting for you</h2>
            <Waiting o={o} />
          </section>
          <AreaCards o={o} />
          <AgentDirectory o={o} />
          <Flow />
          <Readiness o={o} />
        </div>
      )}
    </FpodPage>
  )
}
