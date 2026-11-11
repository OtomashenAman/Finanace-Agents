import { useState } from "react"
import { Link, useParams } from "react-router"
import { Check, CircleAlert, Download, Send, X } from "lucide-react"

import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { AiBadge, AiCard, Card, LoadError, Loading, Pill } from "@/features/service-pod/components/bits"
import { formatDateTime } from "@/features/service-pod/labels"
import { attempt } from "@/features/service-pod/ui"

import { billingApi, type BillingFlag, type SalesInvoice, type SalesInvoiceLine } from "./billing-api"
import { FpodPage } from "./components/fpod-page"
import { useFpodMutation, useSalesInvoice } from "./hooks"
import { formatDate, money, PRICE_SOURCE, SALES_INVOICE_STATUS } from "./labels"

function Flag({ inv, f, lineId }: { inv: SalesInvoice; f: BillingFlag; lineId: string | null }) {
  const clear = useFpodMutation(billingApi.clearFlag)
  const [note, setNote] = useState("")
  const [open, setOpen] = useState(false)
  const canClear = inv.status === "review" && !f.cleared && f.key !== "not_on_schedule"
  return (
    <div className="text-xs">
      <p className={f.cleared ? "text-muted-foreground line-through" : "text-amber-900"}>
        <CircleAlert className="mr-1 inline size-3.5" aria-hidden />
        <strong>{f.label}</strong>: {f.detail}
      </p>
      {f.cleared && (
        <p className="ml-5 text-emerald-700">
          Cleared by {f.cleared.by}: {f.cleared.note}
        </p>
      )}
      {canClear &&
        (open ? (
          <div className="mt-1 ml-5 flex gap-2">
            <Input className="h-8" value={note} onChange={(e) => setNote(e.target.value)} placeholder="What you checked, e.g. the client confirmed" />
            <Button
              size="sm"
              disabled={clear.isPending || note.trim().length < 3}
              onClick={async () => {
                if (await attempt(() => clear.mutateAsync([inv.id, lineId, f.key, note.trim()]), "Cleared.")) setOpen(false)
              }}
            >
              Clear
            </Button>
          </div>
        ) : (
          <Button size="sm" variant="ghost" className="ml-3 h-7" onClick={() => setOpen(true)}>
            Clear with a note
          </Button>
        ))}
    </div>
  )
}

function Override({ inv, ln }: { inv: SalesInvoice; ln: SalesInvoiceLine }) {
  const propose = useFpodMutation(billingApi.proposeOverride)
  const decide = useFpodMutation(billingApi.decideOverride)
  const [editing, setEditing] = useState(false)
  const [price, setPrice] = useState(ln.override_price ?? ln.unit_price)
  const [reason, setReason] = useState("")
  if (inv.status !== "review") {
    return ln.override_status ? (
      <p className="text-xs text-muted-foreground">
        Override {ln.override_status}: {money(ln.override_price, inv.currency)} ({ln.override_reason})
        {ln.override_decided_by_name && ` · by ${ln.override_decided_by_name}`}
      </p>
    ) : null
  }
  if (ln.override_status === "pending") {
    return (
      <div className="rounded-md bg-amber-50 px-2 py-1.5 text-xs text-amber-950">
        <p>
          Override to <strong>{money(ln.override_price, inv.currency)}</strong>: {ln.override_reason}
          <span className="text-amber-800"> · proposed by {ln.override_by_name ?? "client services at intake"}</span>
        </p>
        <div className="mt-1 flex gap-2">
          <Button size="sm" className="h-7" disabled={decide.isPending} onClick={() => attempt(() => decide.mutateAsync([inv.id, ln.id, true, ""]), "Override approved.")}>
            <Check aria-hidden /> Approve override
          </Button>
          <Button size="sm" variant="ghost" className="h-7" disabled={decide.isPending} onClick={() => attempt(() => decide.mutateAsync([inv.id, ln.id, false, ""]), "Override rejected.")}>
            <X aria-hidden /> Reject
          </Button>
        </div>
      </div>
    )
  }
  return editing ? (
    <div className="flex flex-wrap gap-2">
      <Input className="h-8 w-28" inputMode="decimal" value={price} onChange={(e) => setPrice(e.target.value)} aria-label="Override price" />
      <Input className="h-8 min-w-48 flex-1" value={reason} onChange={(e) => setReason(e.target.value)} placeholder="Why (e.g. agreed rate)" />
      <Button
        size="sm"
        className="h-8"
        disabled={propose.isPending || reason.trim().length < 3 || !price}
        onClick={async () => {
          if (await attempt(() => propose.mutateAsync([inv.id, ln.id, price, reason.trim()]), "Override proposed: another person approves it.")) setEditing(false)
        }}
      >
        Propose
      </Button>
    </div>
  ) : (
    <Button size="sm" variant="ghost" className="h-7 px-2 text-xs" onClick={() => setEditing(true)}>
      {ln.price_source === "none" ? "Set a price" : "Override the price"}
    </Button>
  )
}

export function SalesInvoicePage() {
  const { invoiceId } = useParams()
  const q = useSalesInvoice(invoiceId)
  const approve = useFpodMutation(billingApi.approve)
  const voidIt = useFpodMutation(billingApi.void)
  const inv = q.data
  return (
    <FpodPage title={inv ? `Invoice ${inv.reference}` : "Client invoice"}>
      {q.isPending ? (
        <Loading what="the invoice" />
      ) : q.isError || !inv ? (
        <LoadError what="the invoice" />
      ) : (
        <div className="space-y-5">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <div className="flex flex-wrap items-center gap-2 text-sm">
              <Link to="/finance-pod/billing" className="text-primary hover:underline">
                ← Billing
              </Link>
              <Pill label={SALES_INVOICE_STATUS[inv.status][0]} tone={SALES_INVOICE_STATUS[inv.status][1]} />
              <Link to={`/finance-pod/clients/${inv.client_id}`} className="text-primary hover:underline">
                {inv.client_code} {inv.client_name}
              </Link>
              <span className="text-muted-foreground">
                · {inv.submission_reference}
                {inv.report_issued_at && ` · report issued ${formatDateTime(inv.report_issued_at)}`}
              </span>
            </div>
            <div className="flex flex-wrap gap-2">
              <Button size="sm" variant="outline" onClick={() => billingApi.downloadPdf(inv)}>
                <Download aria-hidden /> PDF
              </Button>
              {inv.status === "review" && (
                <>
                  <Button
                    size="sm"
                    variant="ghost"
                    disabled={voidIt.isPending}
                    onClick={() => {
                      const reason = window.prompt("Why void this invoice?")
                      if (reason?.trim()) void attempt(() => voidIt.mutateAsync([inv.id, reason.trim()]), "Voided.")
                    }}
                  >
                    Void
                  </Button>
                  <Button
                    size="sm"
                    disabled={approve.isPending || inv.open_items.length > 0}
                    title={inv.open_items.length ? `Still open: ${inv.open_items.join("; ")}` : undefined}
                    onClick={() => attempt(() => approve.mutateAsync([inv.id]), "Approved: the delivery agent posted and sent it.")}
                  >
                    <Send aria-hidden /> Approve and send
                  </Button>
                </>
              )}
            </div>
          </div>

          {inv.status === "review" && inv.open_items.length > 0 && (
            <p className="rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 text-sm text-amber-950">
              Still open before it can go: {inv.open_items.join(" · ")}
            </p>
          )}
          {inv.status === "sent" && (
            <p className="rounded-lg border border-emerald-200 bg-emerald-50 px-3 py-2 text-sm text-emerald-900">
              Posted to the ERP ({inv.erp_ref}) and emailed to {inv.bill_to_email} {inv.sent_at && formatDateTime(inv.sent_at)}; due {formatDate(inv.due_date)}.
              {inv.viewed_at ? ` The client opened it online ${formatDateTime(inv.viewed_at)}.` : " Not opened online yet."}
              {inv.approved_by_name && ` Approved by ${inv.approved_by_name}.`}
            </p>
          )}
          {inv.void_reason && <p className="text-sm text-red-700">Void: {inv.void_reason}</p>}

          <AiCard
            title="Fee-rule agent"
            hint={`priced each line from the fee schedule or the client's contract, applied ${inv.tax_name ?? "tax"} and checked against the estimate (${formatDateTime(inv.built_at)}).`}
            badge={<AiBadge label="AI agent" />}
          >
            {inv.flags.length === 0 && inv.lines.every((l) => l.flags.length === 0) ? (
              <p className="text-sm text-emerald-800">Nothing unusual.</p>
            ) : (
              <div className="space-y-1.5">
                {inv.flags.map((f) => (
                  <Flag key={f.key} inv={inv} f={f} lineId={null} />
                ))}
              </div>
            )}
          </AiCard>

          <Card title="Lines" hint={`Terms ${inv.payment_terms}${Number(inv.deposit_pct) ? ` · ${Number(inv.deposit_pct)}% deposit` : ""}. The fee schedule itself never changes here.`}>
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead className="text-left text-xs text-muted-foreground">
                  <tr className="border-b border-border">
                    <th className="py-2 pr-3 font-medium">Item</th>
                    <th className="py-2 pr-3 font-medium">Service</th>
                    <th className="py-2 pr-3 text-right font-medium">Qty</th>
                    <th className="py-2 pr-3 text-right font-medium">Published</th>
                    <th className="py-2 pr-3 text-right font-medium">Charged</th>
                    <th className="py-2 text-right font-medium">Amount</th>
                  </tr>
                </thead>
                <tbody>
                  {inv.lines.map((ln) => (
                    <tr key={ln.id} className="border-b border-border/60 align-top">
                      <td className="py-2 pr-3">{ln.item_ref}</td>
                      <td className="space-y-1 py-2 pr-3">
                        <p>
                          {ln.description} <span className="text-xs text-muted-foreground">({ln.service_code} · {ln.stone_type}{ln.carat && `, ${ln.carat} ct`})</span>
                        </p>
                        <p className="text-xs text-muted-foreground">
                          {PRICE_SOURCE[ln.price_source]}
                          {ln.price_note && `: ${ln.price_note}`}
                        </p>
                        {ln.flags.map((f) => (
                          <Flag key={f.key} inv={inv} f={f} lineId={ln.id} />
                        ))}
                        <Override inv={inv} ln={ln} />
                      </td>
                      <td className="py-2 pr-3 text-right tabular-nums">{ln.quantity}</td>
                      <td className="py-2 pr-3 text-right tabular-nums text-muted-foreground">{money(ln.list_price)}</td>
                      <td className="py-2 pr-3 text-right tabular-nums">{money(ln.unit_price)}</td>
                      <td className="py-2 text-right font-medium tabular-nums">{money(ln.amount)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <dl className="mt-3 ml-auto max-w-xs space-y-1 text-sm">
              <div className="flex justify-between">
                <dt>Subtotal</dt>
                <dd className="tabular-nums">{money(inv.subtotal, inv.currency)}</dd>
              </div>
              {Number(inv.discount_total) > 0 && (
                <div className="flex justify-between text-xs text-muted-foreground">
                  <dt>includes contract discounts</dt>
                  <dd className="tabular-nums">{money(inv.discount_total)}</dd>
                </div>
              )}
              <div className="flex justify-between">
                <dt>
                  {inv.tax_name ?? "Tax"} ({Number(inv.tax_rate)}%)
                </dt>
                <dd className="tabular-nums">{money(inv.tax)}</dd>
              </div>
              <div className="flex justify-between border-t border-border pt-1 font-semibold">
                <dt>Total</dt>
                <dd className="tabular-nums">{money(inv.total, inv.currency)}</dd>
              </div>
              {inv.estimate && (
                <div className="flex justify-between text-xs text-muted-foreground">
                  <dt>Estimate given at intake</dt>
                  <dd className="tabular-nums">{money(inv.estimate)}</dd>
                </div>
              )}
            </dl>
          </Card>
        </div>
      )}
    </FpodPage>
  )
}
