import { Link, useParams } from "react-router"
import { CircleCheck, RefreshCw, TriangleAlert } from "lucide-react"

import { Button } from "@/components/ui/button"
import { Card, LoadError, Loading, Pill } from "@/features/service-pod/components/bits"
import { formatDateTime } from "@/features/service-pod/labels"
import { attempt } from "@/features/service-pod/ui"

import { clientsApi } from "./clients-api"
import { FpodPage } from "./components/fpod-page"
import { useClient, useFpodMutation } from "./hooks"
import { formatDate, money, RISK, termsText } from "./labels"

export function ClientPage() {
  const { clientId } = useParams()
  const q = useClient(clientId)
  const sync = useFpodMutation(clientsApi.sync)
  const c = q.data
  return (
    <FpodPage title={c ? `${c.code} ${c.name}` : "Client account"}>
      {q.isPending ? (
        <Loading what="the account" />
      ) : q.isError || !c ? (
        <LoadError what="the account" />
      ) : (
        <div className="space-y-5">
          <div className="flex flex-wrap items-center gap-2 text-sm">
            <Link to="/finance-pod/clients" className="text-primary hover:underline">
              ← Client accounts
            </Link>
            <Pill label={c.status === "on_hold" ? "On hold" : "Active"} tone={c.status === "on_hold" ? "bad" : "good"} />
            {c.risk && <Pill label={RISK[c.risk][0]} tone={RISK[c.risk][1]} />}
            {c.application_id && (
              <Link to={`/finance-pod/clients/applications/${c.application_id}`} className="text-primary hover:underline">
                application
              </Link>
            )}
            {c.open_review_id && (
              <Link to="/finance-pod/credit-reviews" className="font-medium text-amber-800 hover:underline">
                a credit review is waiting
              </Link>
            )}
          </div>

          <div className="grid gap-5 xl:grid-cols-2">
            <Card title="Terms" hint={`Approved by ${c.approved_by_name ?? "the credit controller"}; changed only by the credit controller.`}>
              <p className="text-lg font-semibold">{termsText(c, c.currency)}</p>
              <dl className="mt-3 grid gap-x-4 gap-y-1.5 text-sm sm:grid-cols-2">
                {(
                  [
                    ["Billing email", c.billing_email],
                    ["Tax ID", c.tax_id],
                    ["Address", c.address],
                    ["Last reviewed", c.last_reviewed_at ? formatDateTime(c.last_reviewed_at) : null],
                    ["Next periodic review", formatDate(c.next_review_on)],
                    ["Contacts", c.contacts.map((p) => `${p.name} (${p.email})`).join(", ") || null],
                  ] as [string, string | null][]
                ).map(([k, v]) => (
                  <div key={k}>
                    <dt className="text-xs text-muted-foreground">{k}</dt>
                    <dd className="font-medium break-words">{v ?? "—"}</dd>
                  </div>
                ))}
              </dl>
            </Card>
            <Card
              title="ERP and lab system"
              hint="Set up once by the account agent from the approved record; the monitor corrects the lab system if it drifts."
              actions={
                <Button size="sm" variant="outline" disabled={sync.isPending} onClick={() => attempt(() => sync.mutateAsync([c.id]), "In sync.")}>
                  <RefreshCw aria-hidden /> Sync now
                </Button>
              }
            >
              <dl className="grid gap-x-4 gap-y-1.5 text-sm sm:grid-cols-2">
                <div>
                  <dt className="text-xs text-muted-foreground">ERP reference</dt>
                  <dd className="font-medium">{c.erp_ref ?? "—"}</dd>
                </div>
                <div>
                  <dt className="text-xs text-muted-foreground">Lab system reference</dt>
                  <dd className="font-medium">{c.lab_ref ?? "—"}</dd>
                </div>
                <div>
                  <dt className="text-xs text-muted-foreground">Last written</dt>
                  <dd className="font-medium">{c.synced_at ? formatDateTime(c.synced_at) : "—"}</dd>
                </div>
              </dl>
              {c.sync.in_sync ? (
                <p className="mt-3 flex items-center gap-1.5 text-sm text-emerald-700">
                  <CircleCheck className="size-4" aria-hidden /> Both systems agree.
                </p>
              ) : (
                <div className="mt-3 text-sm text-amber-900">
                  <p className="flex items-center gap-1.5 font-medium">
                    <TriangleAlert className="size-4" aria-hidden /> The lab system differs from the ERP:
                  </p>
                  <ul className="mt-1 list-disc pl-6">
                    {c.sync.differences.map((d) => (
                      <li key={d}>{d}</li>
                    ))}
                  </ul>
                </div>
              )}
            </Card>
          </div>

          <Card title="Billing and payment history" hint="What the monitor reviews the terms from.">
            {c.history.invoices === 0 ? (
              <p className="text-sm text-muted-foreground">No history yet: import it on the Client accounts page.</p>
            ) : (
              <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
                {[
                  ["Invoices", `${c.history.invoices} over ${c.history.months} months`],
                  ["Paid on time", c.history.on_time_rate === null ? "—" : `${Math.round(c.history.on_time_rate * 100)}%`],
                  ["Average days late", c.history.avg_days_late === null ? "—" : String(c.history.avg_days_late)],
                  ["Open balance", money(c.history.open_balance, c.currency)],
                  ["Overdue", `${c.history.overdue} · ${money(c.history.overdue_amount, c.currency)}`],
                  ["Oldest overdue", c.history.worst_overdue_days ? `${c.history.worst_overdue_days} days` : "—"],
                  ["Busiest month", money(c.history.peak_month, c.currency)],
                  ["Credit used", c.credit_limit ? `${Math.round((Number(c.history.open_balance) / Number(c.credit_limit)) * 100)}%` : "—"],
                ].map(([label, value]) => (
                  <div key={label} className="rounded-xl border border-border/80 p-3">
                    <p className="text-xs text-muted-foreground">{label}</p>
                    <p className="mt-0.5 font-semibold tabular-nums">{value}</p>
                  </div>
                ))}
              </div>
            )}
          </Card>
        </div>
      )}
    </FpodPage>
  )
}
