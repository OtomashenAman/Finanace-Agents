import { useState } from "react"
import { Link } from "react-router"
import { FileSpreadsheet, Mail } from "lucide-react"

import { Button } from "@/components/ui/button"
import { Card, Empty, LoadError, Loading, Pill } from "@/features/service-pod/components/bits"
import { formatDateTime } from "@/features/service-pod/labels"
import { attempt } from "@/features/service-pod/ui"
import { cn } from "@/lib/utils"

import { billingApi, type SalesInvoiceStatus } from "./billing-api"
import { FpodPage } from "./components/fpod-page"
import { useBillingMeasures, useFpodMutation, useSalesInvoices, useStatements } from "./hooks"
import { money, SALES_INVOICE_STATUS } from "./labels"

function Kpis() {
  const m = useBillingMeasures().data
  if (!m) return null
  const pct = (n: number) => (m.sent ? `${Math.round((n / m.sent) * 100)}%` : "—")
  const tiles = [
    { label: "Billing accuracy", value: pct(m.accurate), hint: `${m.accurate} of ${m.sent} sent with no price corrected` },
    { label: "Days to invoice (median)", value: m.days_to_invoice_median === null ? "—" : String(m.days_to_invoice_median), hint: `${m.same_day} sent the day the report was issued` },
    { label: "Straight through", value: pct(m.straight_through), hint: "priced and sent with nothing flagged" },
    { label: "With the billing analyst", value: String(m.in_review), hint: `${m.overrides_approved} override(s) approved, ${m.overrides_rejected} rejected` },
  ]
  return (
    <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
      {tiles.map((t) => (
        <div key={t.label} className="rounded-xl border border-border/80 bg-card p-4">
          <p className="text-xs text-muted-foreground">{t.label}</p>
          <p className="mt-1 text-2xl font-semibold tabular-nums">{t.value}</p>
          <p className="mt-1 text-xs text-muted-foreground">{t.hint}</p>
        </div>
      ))}
    </div>
  )
}

function Statements() {
  const list = useStatements()
  const send = useFpodMutation(billingApi.sendStatements)
  return (
    <Card
      title="Monthly statements"
      hint="The delivery agent sends last month's statement to every client with something open, on the 1st."
      actions={
        <Button
          size="sm"
          variant="outline"
          disabled={send.isPending}
          onClick={() => attempt(() => send.mutateAsync([]), (r) => `${r.period}: ${r.sent} statement(s) sent${r.already_sent ? `, ${r.already_sent} already sent` : ""}.`)}
        >
          <Mail aria-hidden /> Send last month's now
        </Button>
      }
    >
      {list.isPending ? (
        <Loading what="statements" />
      ) : list.isError ? (
        <LoadError what="statements" />
      ) : list.data.length === 0 ? (
        <p className="text-sm text-muted-foreground">None sent yet.</p>
      ) : (
        <ul className="divide-y divide-border/60 text-sm">
          {list.data.slice(0, 12).map((s) => (
            <li key={`${s.client_code}-${s.period}`} className="flex justify-between py-1.5">
              <span>
                {s.period} · {s.client_code}
              </span>
              <span className="tabular-nums">
                {s.open_invoices} open · {money(s.open_balance)} <span className="text-xs text-muted-foreground">{formatDateTime(s.created_at)}</span>
              </span>
            </li>
          ))}
        </ul>
      )}
    </Card>
  )
}

export function BillingPage() {
  const [status, setStatus] = useState<SalesInvoiceStatus | null>("review")
  const list = useSalesInvoices(status)
  return (
    <FpodPage title="Billing" subtitle="Clean invoices go out the day the report is issued; flagged ones wait here for the billing analyst.">
      <div className="space-y-5">
        <Kpis />
        <Card
          title="Client invoices"
          actions={
            <div className="flex flex-wrap rounded-lg border border-border p-0.5 text-xs">
              {(["review", "sent", "void", null] as (SalesInvoiceStatus | null)[]).map((k) => (
                <button
                  key={k ?? "all"}
                  type="button"
                  onClick={() => setStatus(k)}
                  className={cn("rounded-md px-2.5 py-1 font-medium", status === k ? "bg-primary text-primary-foreground" : "text-muted-foreground")}
                >
                  {k ? SALES_INVOICE_STATUS[k][0] : "All"}
                </button>
              ))}
            </div>
          }
        >
          {list.isPending ? (
            <Loading what="invoices" />
          ) : list.isError ? (
            <LoadError what="invoices" />
          ) : list.data.length === 0 ? (
            <Empty icon={<FileSpreadsheet className="size-5" />}>
              {status === "review" ? "Nothing waiting for the billing analyst." : "No invoices."}
            </Empty>
          ) : (
            <ul className="divide-y divide-border/60 text-sm">
              {list.data.map((i) => (
                <li key={i.id} className="flex flex-wrap items-start justify-between gap-2 py-2.5">
                  <span className="min-w-0">
                    <Link to={`/finance-pod/billing/${i.id}`} className="font-medium text-primary hover:underline">
                      {i.reference}
                    </Link>{" "}
                    <span className="text-muted-foreground">
                      {i.client_code} {i.client_name} · {i.submission_reference}
                    </span>
                    {i.open_items.length > 0 && <span className="block text-xs text-amber-800">{i.open_items.join(" · ")}</span>}
                  </span>
                  <span className="flex items-center gap-2">
                    <span className="font-medium tabular-nums">{money(i.total, i.currency)}</span>
                    <Pill label={SALES_INVOICE_STATUS[i.status][0]} tone={SALES_INVOICE_STATUS[i.status][1]} />
                  </span>
                </li>
              ))}
            </ul>
          )}
        </Card>
        <Statements />
      </div>
    </FpodPage>
  )
}
