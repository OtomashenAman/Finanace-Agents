import { Link, useNavigate } from "react-router"
import { Mail } from "lucide-react"

import { Button } from "@/components/ui/button"

import type { ArPortfolio } from "../../api"
import { Card, Empty, LoadError, Loading, Pill } from "../../components/bits"
import { WorkflowWorkspace } from "../../components/workspace"
import { useArPortfolio, useCompose, useCreateCase, useCreateDraft } from "../../hooks"
import { CASE_STATUS } from "../../labels"
import { attempt } from "../../ui"
import { fmt, useCanPrepare } from "../shared"
import { Kpi, SourceLine } from "../shared-ui"
import { HOME_LABEL, promiseLabel } from "./meta"

type Customer = ArPortfolio["customers"][number]

const PROMISE_TONE = { overdue: "bad", due: "warn", upcoming: "info", received: "good" } as const

/** Open the customer's case, or open it and draft the payment schedule request at once
 *  (deck AR screen 1: Open Customer / Draft Reminder). The draft still needs a reviewer. */
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
          }, (c) => `${c.reference} opened with a draft: a reviewer approves it before it's sent.`).then(
            (c) => c && void navigate(`/pod/cases/${c.id}`),
          )
        }
      >
        <Mail /> Draft reminder
      </Button>
    </span>
  )
}

/** AR Collections portfolio: open AR, aging, priority customers, next action and promises. */
export function ArPortfolioPage() {
  const { data, isPending, isError } = useArPortfolio()
  const canOpen = useCanPrepare("ar_collections")
  const watched = data?.promises.filter((p) => p.state !== "received") ?? []
  const kept = data?.promises.filter((p) => p.state === "received") ?? []

  return (
    <WorkflowWorkspace workflow="ar_collections" homeLabel={HOME_LABEL}>
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
          <div className="mt-6 grid gap-6 lg:grid-cols-[minmax(0,1fr)_300px]">
            <div className="space-y-6">
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
                      <span className={`text-xs font-medium ${cust.next_action.includes("missed") ? "text-red-800" : ""}`}>
                        {cust.next_action}
                      </span>
                      {cust.open_case ? (
                        <Button asChild size="sm" variant="outline">
                          <Link to={`/pod/cases/${cust.open_case.id}`}>
                            {cust.open_case.reference} · {CASE_STATUS[cust.open_case.status][0]}
                          </Link>
                        </Button>
                      ) : (
                        canOpen && <OpenButtons cust={cust} snapshotId={data.snapshot!.id} />
                      )}
                    </li>
                  ))}
                </ul>
              </Card>
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
            </div>
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
    </WorkflowWorkspace>
  )
}
