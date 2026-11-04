import { useState } from "react"
import { Link, useNavigate } from "react-router"
import { Mail } from "lucide-react"

import { Button } from "@/components/ui/button"

import type { ArPortfolio } from "../../api"
import { Card, Empty, LoadError, Loading, Pill } from "../../components/bits"
import { JourneyStrip } from "../../components/case-steps"
import { WorkflowWorkspace } from "../../components/workspace"
import { useArPortfolio, useCompose, useCreateCase, useCreateDraft } from "../../hooks"
import { CASE_STATUS } from "../../labels"
import { attempt } from "../../ui"
import { fmt } from "../shared"
import { Kpi, SourceLine, StackedBar, Toolbar } from "../shared-ui"
import { HOME_LABEL, promiseLabel } from "./meta"
import { AR_STEPS } from "./steps"

type Customer = ArPortfolio["customers"][number]

const PROMISE_TONE = { overdue: "bad", due: "warn", upcoming: "info", received: "good" } as const

/** Open the customer's case, or open it and draft the payment schedule request at once
 *  (deck AR screen 1: Open Customer / Draft Reminder). The draft is still checked before it goes. */
function OpenButtons({ cust, snapshotId }: { cust: Customer; snapshotId: string }) {
  const create = useCreateCase()
  const compose = useCompose()
  const draft = useCreateDraft()
  const navigate = useNavigate()
  const busy = create.isPending || compose.isPending || draft.isPending
  const open = () =>
    create.mutateAsync({
      workflow: "ar_collections",
      snapshot_id: snapshotId,
      title: cust.name,
      selection: { customer_id: cust.customer_id, invoice_ids: cust.invoices.map((i) => i.id) },
    })
  return (
    <span className="flex gap-2">
      <Button
        size="sm"
        variant="outline"
        disabled={busy}
        onClick={() => void attempt(open, (c) => `${c.reference} opened.`).then((c) => c && void navigate(`/pod/cases/${c.id}`))}
      >
        Open case
      </Button>
      <Button
        size="sm"
        disabled={busy || !cust.email}
        title={cust.email ? undefined : "No verified contact in the source"}
        onClick={() =>
          void attempt(async () => {
            const c = await open()
            const d = await compose.mutateAsync({ caseId: c.id, purpose: "payment_schedule_request" })
            await draft.mutateAsync({
              caseId: c.id,
              draft: {
                audience: "customer",
                purpose: "payment_schedule_request",
                to_email: d.to_email ?? "",
                to_name: d.to_name,
                subject: d.subject,
                body: d.body,
                artifact_ids: [],
              },
            })
            return c
          }, (c) => `${c.reference} opened with a draft: check it before it's sent.`).then(
            (c) => c && void navigate(`/pod/cases/${c.id}`),
          )
        }
      >
        <Mail /> Draft reminder
      </Button>
    </span>
  )
}

const PAGE = 10
type Filter = "all" | "over30" | "over90" | "case" | "nocase"

/** AR Collections portfolio (deck AR screen 1): KPIs, a searchable customer table, aging
 *  and, when there are any, the promises being watched. */
export function ArPortfolioPage() {
  const { data, isPending, isError } = useArPortfolio()
  const [search, setSearch] = useState("")
  const [filter, setFilter] = useState<Filter>("all")
  const [showAll, setShowAll] = useState(false)
  const watched = data?.promises.filter((p) => p.state !== "received") ?? []
  const kept = data?.promises.filter((p) => p.state === "received") ?? []

  const customers = data?.customers ?? []
  const tests: Record<Filter, (c: Customer) => boolean> = {
    all: () => true,
    over30: (c) => c.max_days_overdue > 30,
    over90: (c) => c.max_days_overdue > 90,
    case: (c) => c.open_case !== null,
    nocase: (c) => c.open_case === null,
  }
  const q = search.trim().toLowerCase()
  const rows = customers.filter((c) => tests[filter](c) && (!q || c.name.toLowerCase().includes(q)))
  const visible = showAll ? rows : rows.slice(0, PAGE)

  return (
    <WorkflowWorkspace workflow="ar_collections" homeLabel={HOME_LABEL}>
      <JourneyStrip workflow="ar_collections" home={HOME_LABEL} steps={AR_STEPS} />
      {isPending && <Loading what="the portfolio" />}
      {isError && <LoadError what="the portfolio (you need a role in AR Collections)" />}
      {data && !data.snapshot && <Empty>No snapshot with customers and invoices yet. Import one on Sources.</Empty>}
      {data?.snapshot && (
        <>
          <SourceLine snapshot={data.snapshot} />
          <div className="grid gap-3 sm:grid-cols-4">
            <Kpi label="AR balance" value={fmt(data.ar_balance, data.currency)} />
            <Kpi label="Overdue > 30 days" value={fmt(data.overdue_over_30, data.currency)} />
            <Kpi label="Approved promises" value={fmt(data.approved_promises, data.currency)} />
            <Kpi label="Open exceptions" value={data.open_exceptions} />
          </div>
          <div className="mt-6 grid gap-6 lg:grid-cols-[minmax(0,1fr)_260px]">
            <div className="space-y-6">
              <Card title="Customers with overdue invoices" hint="Every overdue invoice can be collected; over 30 days goes first.">
                <Toolbar<Filter>
                  search={search}
                  onSearch={setSearch}
                  placeholder="Search customer…"
                  active={filter}
                  onFilter={setFilter}
                  filters={[
                    { key: "all", label: "All", count: customers.length },
                    { key: "over30", label: "> 30 d", count: customers.filter(tests.over30).length },
                    { key: "over90", label: "> 90 d", count: customers.filter(tests.over90).length },
                    { key: "case", label: "With case", count: customers.filter(tests.case).length },
                    { key: "nocase", label: "No case", count: customers.filter(tests.nocase).length },
                  ]}
                />
                {rows.length === 0 ? (
                  <Empty>No customer matches.</Empty>
                ) : (
                  <div className="overflow-x-auto">
                    <table className="w-full min-w-[720px] text-sm">
                      <thead>
                        <tr className="border-b text-left text-xs tracking-wide text-muted-foreground uppercase">
                          <th className="py-2 pr-3 font-semibold">Customer</th>
                          <th className="py-2 pr-3 text-right font-semibold">Overdue</th>
                          <th className="py-2 pr-3 text-right font-semibold">Days</th>
                          <th className="py-2 pr-3 text-right font-semibold">Invoices</th>
                          <th className="py-2 pr-3 font-semibold">Next action</th>
                          <th className="py-2" />
                        </tr>
                      </thead>
                      <tbody className="divide-y">
                        {visible.map((cust) => (
                          <tr key={cust.customer_id} className="hover:bg-secondary/30">
                            <td className="py-2 pr-3 font-medium text-brand-navy">{cust.name}</td>
                            <td className="py-2 pr-3 text-right tabular-nums">{fmt(cust.overdue, data.currency)}</td>
                            <td className={`py-2 pr-3 text-right tabular-nums ${cust.max_days_overdue > 90 ? "text-red-800" : ""}`}>{cust.max_days_overdue}</td>
                            <td className="py-2 pr-3 text-right tabular-nums" title={cust.invoices.map((i) => i.number).join(", ")}>
                              {cust.invoices.length}
                            </td>
                            <td className={`py-2 pr-3 text-xs ${cust.next_action.includes("missed") ? "font-semibold text-red-800" : ""}`}>{cust.next_action}</td>
                            <td className="py-2 text-right">
                              {cust.open_case ? (
                                <Button asChild size="sm" variant="outline">
                                  <Link to={`/pod/cases/${cust.open_case.id}`}>
                                    {cust.open_case.reference} · {CASE_STATUS[cust.open_case.status][0]}
                                  </Link>
                                </Button>
                              ) : (
                                <OpenButtons cust={cust} snapshotId={data.snapshot!.id} />
                              )}
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                )}
                {rows.length > PAGE && (
                  <Button size="sm" variant="ghost" className="mt-2" onClick={() => setShowAll((v) => !v)}>
                    {showAll ? "Show fewer" : `Show all ${rows.length}`}
                  </Button>
                )}
              </Card>
              {data.promises.length > 0 && (
                <Card
                  title="Promises to watch"
                  hint="Approved payment dates. Kept only when cash shows: a verified bank posting or a newer source, never the promise itself."
                >
                  {watched.length === 0 && <Empty>No open promises.</Empty>}
                  <ul className="divide-y">
                    {watched.map((p) => (
                      <li key={`${p.case_id}-${p.invoice_number}-${p.expected_date}-${p.amount}`} className="flex flex-wrap items-center gap-2 py-2 text-sm">
                        <Pill label={promiseLabel(p)} tone={PROMISE_TONE[p.state]} />
                        <span className="font-medium">{p.customer}</span>
                        <span>
                          {p.invoice_number} · {fmt(p.amount, data.currency)} on {p.expected_date}
                        </span>
                        <Link to={`/pod/cases/${p.case_id}`} className="ml-auto text-xs text-primary hover:underline">
                          {p.case_reference}
                        </Link>
                      </li>
                    ))}
                  </ul>
                  {kept.length > 0 && (
                    <p className="mt-2 border-t pt-2 text-xs text-muted-foreground">
                      Kept: {kept.map((p) => `${p.invoice_number} ${fmt(p.amount, data.currency)} (${p.received_by})`).join(" · ")}
                    </p>
                  )}
                </Card>
              )}
            </div>
            <Card title="Aging">
              <StackedBar items={data.aging} currency={data.currency} />
            </Card>
          </div>
        </>
      )}
    </WorkflowWorkspace>
  )
}
