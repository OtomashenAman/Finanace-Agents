import { Link, useNavigate } from "react-router"

import { AppPage } from "@/components/layout/app-page"
import { Button } from "@/components/ui/button"

import { Card, Empty, LoadError, Loading, PodTabs } from "../../components/bits"
import { useArPortfolio, useCreateCase } from "../../hooks"
import { CASE_STATUS } from "../../labels"
import { attempt } from "../../ui"
import { fmt, useCanPrepare } from "../shared"
import { Kpi, SourceLine } from "../shared-ui"

/** AR Collections portfolio: open AR, aging, priority customers and next action. */
export function ArPortfolioPage() {
  const { data, isPending, isError } = useArPortfolio()
  const create = useCreateCase()
  const navigate = useNavigate()
  const canOpen = useCanPrepare("ar_collections")

  return (
    <AppPage title="Service POD" subtitle="AR Collections: who owes what, how late, and the next step for each customer.">
      <PodTabs />
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
          <div className="mt-6 grid gap-6 lg:grid-cols-[minmax(0,1fr)_280px]">
            <Card title="Priority customers" hint="Every overdue invoice can be collected; over 30 days goes first.">
              {data.customers.length === 0 && <Empty>No overdue invoices.</Empty>}
              <ul className="divide-y">
                {data.customers.map((cust) => (
                  <li key={cust.customer_id} className="flex flex-col gap-2 py-3 text-sm sm:flex-row sm:items-center">
                    <div className="min-w-0 flex-1">
                      <p className="font-semibold text-brand-navy">{cust.name}</p>
                      <p className="text-xs text-muted-foreground">
                        {fmt(cust.overdue, data.currency)} · {cust.max_days_overdue} days overdue ·{" "}
                        {cust.invoices.map((i) => i.number).join(", ")}
                      </p>
                    </div>
                    <span className="text-xs font-medium">{cust.next_action}</span>
                    {cust.open_case ? (
                      <Button asChild size="sm" variant="outline">
                        <Link to={`/pod/cases/${cust.open_case.id}`}>
                          {cust.open_case.reference} · {CASE_STATUS[cust.open_case.status][0]}
                        </Link>
                      </Button>
                    ) : (
                      canOpen && (
                        <Button
                          size="sm"
                          disabled={create.isPending}
                          onClick={() =>
                            void attempt(
                              () =>
                                create.mutateAsync({
                                  workflow: "ar_collections",
                                  snapshot_id: data.snapshot!.id,
                                  title: cust.name,
                                  selection: { customer_id: cust.customer_id, invoice_ids: cust.invoices.map((i) => i.id) },
                                }),
                              (c) => `${c.reference} opened.`,
                            ).then((c) => c && void navigate(`/pod/cases/${c.id}`))
                          }
                        >
                          Open case
                        </Button>
                      )
                    )}
                  </li>
                ))}
              </ul>
            </Card>
            <Card title="Aging">
              <ul className="space-y-1 text-sm">
                {data.aging.map((b) => (
                  <li key={b.label} className="flex justify-between tabular-nums">
                    <span>{b.label}</span>
                    <span>
                      {fmt(b.amount, data.currency)} <span className="text-xs text-muted-foreground">({b.count})</span>
                    </span>
                  </li>
                ))}
              </ul>
            </Card>
          </div>
        </>
      )}
    </AppPage>
  )
}
