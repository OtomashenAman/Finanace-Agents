import { Link } from "react-router"
import { Bot, Hammer, ShieldCheck, User } from "lucide-react"

import { Card, Empty, LoadError, Loading } from "@/features/service-pod/components/bits"

import { useFinanceDashboard, useFinanceMe } from "./hooks"
import { formatMeasure, KIND_META } from "./labels"
import { ErpSnapshots } from "./components/erp-snapshots"
import { NewCase } from "./components/new-case"
import { SanctionsCard } from "./components/sanctions-card"
import { FinancePage } from "./components/finance-page"
import { cn } from "@/lib/utils"

function MyAccess() {
  const { data: me } = useFinanceMe()
  if (!me) return null
  return (
    <Card title="My capacities" hint="What you may do in the Finance POD. Segregation of duties applies to everyone.">
      {me.is_admin ? (
        <p className="flex items-center gap-2 text-sm">
          <ShieldCheck className="size-4 text-emerald-600" aria-hidden />
          Finance Admin: every capacity, every entity. You still can't approve your own work where the requirement needs a
          second person.
        </p>
      ) : (
        <ul className="flex flex-wrap gap-2">
          {me.capacities.map((c) => (
            <li key={c.capacity} className="rounded-full border border-border px-3 py-1 text-xs">
              <span className="font-medium">{c.label}</span>{" "}
              <span className="text-muted-foreground">
                {c.entities === null ? "all entities" : c.entities.map((e) => e.code).join(", ")}
              </span>
            </li>
          ))}
        </ul>
      )}
    </Card>
  )
}

export function FinanceDashboardPage() {
  const { data, isLoading, isError } = useFinanceDashboard()
  const { data: me } = useFinanceMe()

  return (
    <FinancePage
      title="Finance POD"
      subtitle="Accounts Payable and Receivable agents: each step as the requirement draws it, an agent prepares and a person decides."
    >
      {isLoading && <Loading what="the Finance POD" />}
      {isError && <LoadError what="the Finance POD" />}
      {data && (
        <div className="space-y-4">
          <NewCase />
          <Card title="Waiting on me" hint="Steps you can act on now, oldest case first.">
            {data.my_queue.length === 0 ? (
              <Empty icon={<User className="size-5" />}>Nothing waits on you right now.</Empty>
            ) : (
              <ul className="divide-y divide-border/70">
                {data.my_queue.map((item) => (
                  <li key={`${item.case_id}-${item.step_key}`} className="flex items-center justify-between gap-3 py-2">
                    <div className="flex min-w-0 items-center gap-2">
                      <span className={cn("rounded px-1.5 py-0.5 text-[10px] font-bold uppercase", KIND_META[item.kind].chip)}>
                        {item.kind === "agent" ? <Bot className="inline size-3" aria-hidden /> : null} {item.step_key}
                      </span>
                      <span className="truncate text-sm">
                        <Link to={`/finance/cases/${item.case_id}`} className="font-medium text-primary hover:underline">
                          {item.reference}
                        </Link>{" "}
                        {item.step_title} · {item.case_title}
                      </span>
                    </div>
                    <span className="shrink-0 text-xs text-muted-foreground">
                      {new Date(item.waiting_since).toLocaleDateString()}
                    </span>
                  </li>
                ))}
              </ul>
            )}
          </Card>

          <Card title="Workflows" hint="One per phase of the requirement, with the measures it names.">
            {data.workflows.length === 0 ? (
              <Empty icon={<Hammer className="size-5" />}>
                The AP agents (Purchase Request &amp; PO, Invoice Matching, Month-End Close) are being built. Their cases
                will show here.
              </Empty>
            ) : (
              <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
                {data.workflows.map((w) => (
                  <Link
                    key={w.key}
                    to={`/finance/cases?workflow=${w.key}`}
                    className="rounded-lg border border-border/80 p-3 transition-colors hover:border-primary/50"
                  >
                    <div className="flex items-center justify-between">
                      <h3 className="text-sm font-semibold">{w.name}</h3>
                      <span className="font-mono text-xs text-muted-foreground">{w.prefix}</span>
                    </div>
                    <p className="mt-1 text-xs text-muted-foreground">{w.description}</p>
                    <dl className="mt-2 grid grid-cols-3 gap-2 text-center text-xs">
                      <div>
                        <dt className="text-muted-foreground">Open</dt>
                        <dd className="text-base font-semibold">{w.open}</dd>
                      </div>
                      <div>
                        <dt className="text-muted-foreground">Approved</dt>
                        <dd className="text-base font-semibold">{w.approved}</dd>
                      </div>
                      <div>
                        <dt className="text-muted-foreground">Done 30d</dt>
                        <dd className="text-base font-semibold">{w.completed_30d}</dd>
                      </div>
                    </dl>
                    {w.measures.length > 0 && (
                      <ul className="mt-2 space-y-0.5 border-t border-border/60 pt-2 text-xs">
                        {w.measures.map((m) => (
                          <li key={m.id} className="flex justify-between">
                            <span className="text-muted-foreground">{m.label}</span>
                            <span className="font-medium">{formatMeasure(m.value, m.unit)}</span>
                          </li>
                        ))}
                      </ul>
                    )}
                  </Link>
                ))}
              </div>
            )}
          </Card>

          {me?.is_admin && <ErpSnapshots />}
          {me?.is_admin && <SanctionsCard />}

          <MyAccess />
        </div>
      )}
    </FinancePage>
  )
}
