import { useState } from "react"
import { Link, useNavigate, useParams } from "react-router"
import { CircleAlert, Download, Info, PhoneCall, ShieldCheck, Trash2, XCircle } from "lucide-react"

import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { AiBadge, AiCard, Card, GuardedButton, LoadError, Loading, Pill } from "@/features/service-pod/components/bits"
import { formatDateTime } from "@/features/service-pod/labels"
import { attempt, selectClass } from "@/features/service-pod/ui"
import { cn } from "@/lib/utils"

import { FpodPage } from "./components/fpod-page"
import { useFpodMutation, usePaymentRun } from "./hooks"
import { formatDate, money, RUN_STATUS } from "./labels"
import { CALLBACK_SOURCES } from "./procurement-api"
import { paymentsApi, type PaymentRun, type RunItem } from "./payments-api"

const SEVERITY = {
  block: { icon: XCircle, cls: "text-red-700" },
  review: { icon: CircleAlert, cls: "text-amber-800" },
  info: { icon: Info, cls: "text-muted-foreground" },
} as const

function Callback({ run, item }: { run: PaymentRun; item: RunItem }) {
  const confirm = useFpodMutation(paymentsApi.callback)
  const [f, setF] = useState({ phone: "", source: CALLBACK_SOURCES[0], contact: "", confirmed_last4: "", note: "" })
  return (
    <div className="mt-2 space-y-2 rounded-lg border border-red-200 bg-red-50/60 p-3">
      <p className="flex items-center gap-1.5 text-xs font-semibold text-red-900">
        <PhoneCall className="size-3.5" aria-hidden /> AP analyst: call back on a number we already hold (never one from the vendor's latest message)
      </p>
      <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-4">
        <Input placeholder="Number called" value={f.phone} onChange={(e) => setF({ ...f, phone: e.target.value })} />
        <select className={selectClass} value={f.source} onChange={(e) => setF({ ...f, source: e.target.value })}>
          {CALLBACK_SOURCES.map((s) => (
            <option key={s}>{s}</option>
          ))}
        </select>
        <Input placeholder="Who you spoke to" value={f.contact} onChange={(e) => setF({ ...f, contact: e.target.value })} />
        <Input placeholder={`Last 4 they confirm (on file …${item.account_last4})`} maxLength={4} value={f.confirmed_last4} onChange={(e) => setF({ ...f, confirmed_last4: e.target.value })} />
      </div>
      <Button
        size="sm"
        disabled={confirm.isPending || !f.phone || !f.contact || f.confirmed_last4.length !== 4}
        onClick={() => attempt(() => confirm.mutateAsync([run, item.id, f]), "Call-back recorded.")}
      >
        Record call-back
      </Button>
    </div>
  )
}

function Items({ run }: { run: PaymentRun }) {
  const exclude = useFpodMutation(paymentsApi.exclude)
  const editable = run.status === "proposed"
  const groups = [...new Set(run.items.map((i) => i.group_key))]
  return (
    <div className="space-y-4">
      {groups.map((g) => (
        <section key={g} className="rounded-xl border border-border/80">
          <header className="flex items-center justify-between border-b border-border/70 bg-muted/30 px-3 py-2 text-sm">
            <span className="font-semibold">{g}</span>
            <span className="tabular-nums">
              {money(run.groups.find((x) => x.key === g)?.total ?? 0, run.groups.find((x) => x.key === g)?.currency)}
            </span>
          </header>
          <ul className="divide-y divide-border/60">
            {run.items
              .filter((i) => i.group_key === g)
              .map((i) => (
                <li key={i.id} className={cn("px-3 py-2.5 text-sm", i.excluded && "opacity-55")}>
                  <div className="flex flex-wrap items-start justify-between gap-2">
                    <div>
                      <p className="font-medium">
                        {i.vendor_name}{" "}
                        <Link to={`/finance-pod/invoices/${i.invoice_id}`} className="text-xs font-normal text-primary hover:underline">
                          {i.vendor_invoice_number ?? i.invoice_reference}
                        </Link>
                      </p>
                      <p className="text-xs text-muted-foreground">
                        {i.reason === "discount"
                          ? `Early-pay discount until ${formatDate(i.discount_until)}`
                          : i.reason === "overdue"
                            ? `Overdue since ${formatDate(i.due_date)}`
                            : `Due ${formatDate(i.due_date)}`}
                        {i.account_last4 && ` · to account …${i.account_last4}`}
                        {i.payment_ref && ` · ref ${i.payment_ref}`}
                      </p>
                    </div>
                    <div className="text-right">
                      <p className="font-semibold tabular-nums">{money(i.amount, i.currency)}</p>
                      {Number(i.discount) > 0 && (
                        <p className="text-xs text-emerald-700">
                          {money(i.invoice_total)} less {money(i.discount)}
                        </p>
                      )}
                    </div>
                  </div>
                  {i.flags.length > 0 && (
                    <ul className="mt-1.5 flex flex-wrap gap-x-4 gap-y-1">
                      {i.flags.map((f) => {
                        const { icon: Icon, cls } = SEVERITY[f.severity]
                        return (
                          <li key={f.key} className={cn("flex items-center gap-1 text-xs", cls)}>
                            <Icon className="size-3.5" aria-hidden /> {f.label}
                          </li>
                        )
                      })}
                    </ul>
                  )}
                  {i.callback_status === "confirmed" && (
                    <p className="mt-1 flex items-center gap-1 text-xs text-emerald-700">
                      <ShieldCheck className="size-3.5" aria-hidden /> {i.callback_note} ({i.callback_by_name})
                    </p>
                  )}
                  {i.excluded && <p className="mt-1 text-xs text-muted-foreground">Not in this run: {i.exclude_reason}</p>}
                  {editable && !i.excluded && i.callback_status === "needed" && <Callback run={run} item={i} />}
                  {editable && i.bank_name && (
                    <Button
                      size="sm"
                      variant="ghost"
                      className="mt-1 h-7 px-2 text-xs"
                      disabled={exclude.isPending}
                      onClick={() => {
                        const reason = i.excluded ? "" : (window.prompt("Why leave it out of this run?") ?? "")
                        if (i.excluded || reason.trim())
                          void attempt(() => exclude.mutateAsync([run, i.id, !i.excluded, reason]), i.excluded ? "Back in the run." : "Left out of the run.")
                      }}
                    >
                      {i.excluded ? "Put back in the run" : "Leave out of this run"}
                    </Button>
                  )}
                </li>
              ))}
          </ul>
        </section>
      ))}
    </div>
  )
}

function Release({ run }: { run: PaymentRun }) {
  const approve = useFpodMutation(paymentsApi.approve)
  const cancel = useFpodMutation(paymentsApi.cancel)
  const [note, setNote] = useState("")
  const live = run.status === "proposed" || run.status === "partly_approved"
  const cashOk = run.cash_available === null || run.groups.every((g) => Number(g.total) <= Number(run.cash_available))
  return (
    <Card title="Treasury release" hint="Two different people release every run. Agents can't.">
      <div className="space-y-3 text-sm">
        <dl className="grid gap-2 sm:grid-cols-3">
          <div className="rounded-lg bg-muted/40 p-2">
            <dt className="text-xs text-muted-foreground">To pay</dt>
            <dd className="text-lg font-semibold tabular-nums">{money(run.total)}</dd>
          </div>
          <div className="rounded-lg bg-muted/40 p-2">
            <dt className="text-xs text-muted-foreground">Discounts taken</dt>
            <dd className="text-lg font-semibold tabular-nums text-emerald-700">{money(run.discounts)}</dd>
          </div>
          <div className={cn("rounded-lg p-2", cashOk ? "bg-muted/40" : "bg-red-50")}>
            <dt className="text-xs text-muted-foreground">Cash available</dt>
            <dd className="text-lg font-semibold tabular-nums">{run.cash_available === null ? "not set" : money(run.cash_available)}</dd>
          </div>
        </dl>
        <ol className="space-y-1">
          {[0, 1].map((n) => {
            const a = run.approvals[n]
            return (
              <li key={n} className="flex items-center gap-2">
                <span className={cn("flex size-5 items-center justify-center rounded-full text-[11px] font-semibold", a ? "bg-emerald-600 text-white" : "bg-muted text-muted-foreground")}>
                  {n + 1}
                </span>
                {a ? (
                  <span>
                    {a.name} released {formatDateTime(a.at)}
                    {a.note && ` · ${a.note}`}
                    {a.self_approval && <Pill label="same person: self-approval" tone="warn" />}
                  </span>
                ) : (
                  <span className="text-muted-foreground">{n === 0 ? "First release" : "Second release, by a different person"}</span>
                )}
              </li>
            )
          })}
        </ol>
        {run.release_blockers.length > 0 && live && (
          <ul className="space-y-1">
            {run.release_blockers.map((b) => (
              <li key={b} className="flex items-start gap-1.5 text-red-700">
                <XCircle className="mt-0.5 size-4 shrink-0" aria-hidden /> {b}
              </li>
            ))}
          </ul>
        )}
        {live && (
          <div className="flex flex-wrap items-center gap-2">
            <Input className="max-w-sm" placeholder="Note (optional)" value={note} onChange={(e) => setNote(e.target.value)} />
            <GuardedButton
              reason={run.can_approve}
              disabled={approve.isPending}
              onClick={() =>
                attempt(() => approve.mutateAsync([run, note]), run.approvals.length ? "Released: paid and remittances sent." : "First release given.")
              }
            >
              <ShieldCheck aria-hidden /> {run.approvals.length ? "Second release" : "First release"}
            </GuardedButton>
            <Button
              size="sm"
              variant="ghost"
              disabled={cancel.isPending}
              onClick={() => {
                const reason = window.prompt("Why cancel this run?")
                if (reason?.trim()) void attempt(() => cancel.mutateAsync([run, reason.trim()]), "Run cancelled.")
              }}
            >
              Cancel run
            </Button>
          </div>
        )}
        {run.status === "released" && (
          <Button size="sm" variant="outline" onClick={() => paymentsApi.bankFile(run)}>
            <Download aria-hidden /> Bank file (CSV) for the bank portal
          </Button>
        )}
        {run.cancelled_reason && <p className="text-muted-foreground">Cancelled: {run.cancelled_reason}</p>}
      </div>
    </Card>
  )
}

function DeleteRun({ run }: { run: PaymentRun }) {
  const navigate = useNavigate()
  const remove = useFpodMutation(paymentsApi.remove)
  return (
    <Button
      size="sm"
      variant="ghost"
      className="ml-auto text-red-700"
      disabled={remove.isPending}
      onClick={async () => {
        const note =
          run.status === "released"
            ? `\n\nIts ${run.items.filter((i) => !i.excluded).length} paid invoice(s) go back to "ready to pay". Remittance emails already sent can't be recalled.`
            : "\n\nIts invoices go back to the pool for the next run."
        if (!window.confirm(`Delete ${run.reference}?${note}`)) return
        const r = await attempt(() => remove.mutateAsync([[run.id]]), `${run.reference} deleted.`)
        if (r) navigate("/finance-pod/payments")
      }}
    >
      <Trash2 aria-hidden /> Delete run
    </Button>
  )
}

export function PaymentRunPage() {
  const { runId } = useParams()
  const q = usePaymentRun(runId)
  const run = q.data
  return (
    <FpodPage title={run ? `Payment run ${run.reference}` : "Payment run"}>
      {q.isPending ? (
        <Loading what="the run" />
      ) : q.isError || !run ? (
        <LoadError what="the run" />
      ) : (
        <div className="space-y-5">
          <div className="flex flex-wrap items-center gap-2 text-sm">
            <Link to="/finance-pod/payments" className="text-primary hover:underline">
              ← All runs
            </Link>
            <Pill label={RUN_STATUS[run.status][0]} tone={RUN_STATUS[run.status][1]} />
            <span className="text-muted-foreground">
              proposed {formatDateTime(run.created_at)} · looks {run.horizon_days} days ahead
            </span>
            <DeleteRun run={run} />
          </div>
          <div className="grid gap-5 xl:grid-cols-[minmax(0,1fr)_380px]">
            <AiCard
              title="Proposed payments"
              hint="Grouped by currency and bank. Each payment carries the payment agent's risk checks: red blocks the release, amber is for the reviewer."
              badge={<AiBadge label="Payment agent" />}
            >
              <Items run={run} />
            </AiCard>
            <div>
              <Release run={run} />
            </div>
          </div>
        </div>
      )}
    </FpodPage>
  )
}
