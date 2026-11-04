import { useRef, useState } from "react"
import { CircleAlert, CircleCheck, FileCheck2, Pencil, Send, Sparkles, XCircle } from "lucide-react"

import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { AiBadge, AiCard, Field, GuardedButton, LoadError, Loading, Pill } from "@/features/service-pod/components/bits"
import { formatDateTime } from "@/features/service-pod/labels"
import { attempt } from "@/features/service-pod/ui"

import type { PurchaseRequest } from "../api"
import { useFpodMutation, useRequestPo, useSourcing } from "../hooks"
import { formatDate, money, PO_STATUS } from "../labels"
import { procurementApi, type PoUpdate, type PurchaseOrder } from "../procurement-api"
import { PoInvoices } from "./po-invoices"
import { ReceiptsSection } from "./receipts-section"

const SOURCE: Record<string, string> = {
  contract: "contract price",
  quote: "from the quote",
  estimate: "requester's estimate",
  buyer: "set by the buyer",
}

function EditPo({ po, onDone }: { po: PurchaseOrder; onDone: () => void }) {
  const save = useFpodMutation(procurementApi.updatePo)
  const [form, setForm] = useState<PoUpdate>({
    lines: po.lines.map((l) => ({
      description: l.description,
      quantity: l.quantity,
      unit: l.unit,
      unit_price: l.unit_price,
      category: l.category,
    })),
    payment_terms: po.payment_terms,
    delivery_date: po.delivery_date,
    notes: po.notes,
  })
  const total = form.lines.reduce((s, l) => s + Number(l.quantity || 0) * Number(l.unit_price || 0), 0)
  return (
    <div className="space-y-3">
      <table className="w-full text-sm">
        <thead className="text-left text-xs text-muted-foreground">
          <tr>
            <th className="pb-1 font-medium">Description</th>
            <th className="w-24 pb-1 font-medium">Qty</th>
            <th className="w-32 pb-1 font-medium">Unit price</th>
          </tr>
        </thead>
        <tbody>
          {form.lines.map((l, i) => (
            <tr key={i}>
              <td className="py-1 pr-2">{l.description}</td>
              <td className="py-1 pr-2">
                <Input
                  aria-label={`Line ${i + 1} quantity`}
                  inputMode="decimal"
                  value={l.quantity}
                  onChange={(e) =>
                    setForm({ ...form, lines: form.lines.map((x, n) => (n === i ? { ...x, quantity: e.target.value } : x)) })
                  }
                />
              </td>
              <td className="py-1">
                <Input
                  aria-label={`Line ${i + 1} unit price`}
                  inputMode="decimal"
                  value={l.unit_price}
                  onChange={(e) =>
                    setForm({ ...form, lines: form.lines.map((x, n) => (n === i ? { ...x, unit_price: e.target.value } : x)) })
                  }
                />
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      <p className="text-sm">
        Total <strong className="tabular-nums">{money(total, po.currency)}</strong>
        {po.quote_total && ` · the quote: ${money(po.quote_total, po.currency)}`}
      </p>
      <div className="grid gap-2 sm:grid-cols-3">
        <Field label="Payment terms">
          <Input value={form.payment_terms ?? ""} onChange={(e) => setForm({ ...form, payment_terms: e.target.value || null })} />
        </Field>
        <Field label="Delivery date">
          <Input type="date" value={form.delivery_date ?? ""} onChange={(e) => setForm({ ...form, delivery_date: e.target.value || null })} />
        </Field>
        <Field label="Notes to the vendor">
          <Input value={form.notes ?? ""} onChange={(e) => setForm({ ...form, notes: e.target.value || null })} />
        </Field>
      </div>
      <div className="flex gap-2">
        <Button
          size="sm"
          disabled={save.isPending}
          onClick={async () => {
            const ok = await attempt(() => save.mutateAsync([po.id, po.version, form]), "PO saved.")
            if (ok) onDone()
          }}
        >
          Save
        </Button>
        <Button size="sm" variant="outline" onClick={onDone}>
          Cancel
        </Button>
      </div>
    </div>
  )
}

function Acknowledge({ po }: { po: PurchaseOrder }) {
  const ack = useFpodMutation(procurementApi.acknowledgePo)
  const [note, setNote] = useState("")
  const [on, setOn] = useState(new Date().toISOString().slice(0, 10))
  const fileRef = useRef<HTMLInputElement>(null)
  return (
    <div className="grid gap-2 rounded-lg bg-muted/30 p-3 sm:grid-cols-[1fr_160px_auto]">
      <Field label="Vendor's acknowledgement">
        <Input value={note} onChange={(e) => setNote(e.target.value)} placeholder="e.g. Confirmed by email, delivery 12 Dec" />
      </Field>
      <Field label="Received on">
        <Input type="date" value={on} onChange={(e) => setOn(e.target.value)} />
      </Field>
      <div className="flex items-end gap-2">
        <Input ref={fileRef} type="file" className="max-w-[180px]" aria-label="Acknowledgement file (optional)" />
        <Button
          size="sm"
          disabled={ack.isPending}
          onClick={() =>
            attempt(
              () => ack.mutateAsync([po.id, po.version, note, on || null, fileRef.current?.files?.[0] ?? null]),
              "Acknowledgement logged.",
            )
          }
        >
          <FileCheck2 aria-hidden /> Log
        </Button>
      </div>
    </div>
  )
}

/** the PO agent's draft, approval above the limit, issue and acknowledgement. */
export function PoPanel({ r }: { r: PurchaseRequest }) {
  const show = r.status === "approved" || r.status === "ordered"
  const po = useRequestPo(r.id, show)
  const sourcing = useSourcing(r.id, show)
  const draft = useFpodMutation(procurementApi.draftPo)
  const action = useFpodMutation(procurementApi.poAction)
  const cancel = useFpodMutation(procurementApi.cancelPo)
  const [editing, setEditing] = useState(false)
  if (!show) return null
  if (po.isPending) return <Loading what="the purchase order" />
  if (po.isError) return <LoadError what="the purchase order" />
  const p = po.data
  const ready = sourcing.data?.status === "chosen"

  if (!p || p.status === "cancelled") {
    return (
      <AiCard title="Purchase order" hint="the PO agent drafts the PO from the approved request and the buyer's choice." badge={<AiBadge label="PO agent" />}>
        {p && <p className="mb-2 text-sm text-muted-foreground">{p.reference} was cancelled: {p.cancelled_reason}</p>}
        <GuardedButton
          reason={ready ? null : "Choose the vendor first (an onboarding vendor must be active)."}
          disabled={draft.isPending}
          onClick={() => attempt(() => draft.mutateAsync([r.id]), "The PO agent drafted the PO.")}
        >
          <Sparkles aria-hidden /> Draft the PO
        </GuardedButton>
      </AiCard>
    )
  }

  const blocking = p.issues.filter((i) => i.blocking)
  return (
    <AiCard
      title={`Purchase order ${p.reference}`}
      hint={`To ${p.vendor_name} (${p.vendor_code}), ${p.vendor_email ?? "no email"} · drafted by the PO agent for ${p.drafted_by_name}`}
      badge={<AiBadge label="PO agent" />}
      actions={<Pill label={PO_STATUS[p.status][0]} tone={PO_STATUS[p.status][1]} />}
    >
      <div className="space-y-4 text-sm">
        {editing ? (
          <EditPo po={p} onDone={() => setEditing(false)} />
        ) : (
          <>
            <table className="w-full text-sm">
              <thead className="text-left text-xs text-muted-foreground">
                <tr className="border-b border-border">
                  <th className="py-1 pr-2 font-medium">#</th>
                  <th className="py-1 pr-2 font-medium">Description</th>
                  <th className="py-1 pr-2 text-right font-medium">Qty</th>
                  <th className="py-1 pr-2 text-right font-medium">Unit price</th>
                  <th className="py-1 text-right font-medium">Amount</th>
                </tr>
              </thead>
              <tbody>
                {p.lines.map((l, i) => (
                  <tr key={i} className="border-b border-border/50 align-top">
                    <td className="py-1 pr-2 text-muted-foreground">{i + 1}</td>
                    <td className="py-1 pr-2">
                      {l.description}
                      <span className="block text-xs text-muted-foreground">{SOURCE[l.price_source] ?? l.price_source}</span>
                    </td>
                    <td className="py-1 pr-2 text-right tabular-nums">
                      {Number(l.quantity)} {l.unit ?? ""}
                    </td>
                    <td className="py-1 pr-2 text-right tabular-nums">{money(l.unit_price)}</td>
                    <td className="py-1 text-right tabular-nums">{money(l.amount)}</td>
                  </tr>
                ))}
              </tbody>
              <tfoot>
                <tr>
                  <td colSpan={4} className="py-1 pr-2 text-right font-medium">
                    Total
                  </td>
                  <td className="py-1 text-right font-semibold tabular-nums">{money(p.total, p.currency)}</td>
                </tr>
              </tfoot>
            </table>
            <dl className="grid gap-1 text-xs sm:grid-cols-2">
              <div>Payment terms: <strong>{p.payment_terms ?? "—"}</strong></div>
              <div>Delivery: <strong>{formatDate(p.delivery_date)}</strong></div>
              <div>
                Coding: <strong>{[p.cost_centre_code, p.lab_code, p.project_code, p.grant_code].filter(Boolean).join(" · ")}</strong>
              </div>
              {p.erp_ref && (
                <div>
                  ERP: <strong>{p.erp_system} {p.erp_ref}</strong> · issued {formatDateTime(p.issued_at!)}
                </div>
              )}
              {p.approved_by_name && (
                <div>
                  Approved by <strong>{p.approved_by_name}</strong> as {p.approval_capacity}
                  {p.approval_acting_for && ` for ${p.approval_acting_for}`}
                  {p.self_approval && " (self-approval allowed)"}
                </div>
              )}
              {p.acknowledged_at && (
                <div className="sm:col-span-2">
                  Acknowledged {formatDateTime(p.acknowledged_at)}: {p.acknowledgement_note}
                </div>
              )}
            </dl>
          </>
        )}
        {p.issues.length > 0 && (
          <ul className="space-y-1">
            {p.issues.map((i) => (
              <li key={i.message} className={i.blocking ? "flex gap-1.5 text-red-700" : "flex gap-1.5 text-amber-800"}>
                {i.blocking ? <XCircle className="mt-0.5 size-4 shrink-0" /> : <CircleAlert className="mt-0.5 size-4 shrink-0" />}
                {i.message}
              </li>
            ))}
          </ul>
        )}
        {!editing && (
          <div className="flex flex-wrap gap-2">
            {p.status === "draft" && (
              <>
                <Button size="sm" variant="outline" onClick={() => setEditing(true)}>
                  <Pencil aria-hidden /> Edit
                </Button>
                <GuardedButton
                  reason={blocking.length ? "Fix the blocking issues first." : null}
                  disabled={action.isPending}
                  onClick={() => attempt(() => action.mutateAsync([p.id, "confirm", p.version]), "PO confirmed.")}
                >
                  <CircleCheck aria-hidden /> Confirm PO
                </GuardedButton>
              </>
            )}
            {p.status === "pending_approval" && (
              <GuardedButton
                reason={p.can_approve}
                disabled={action.isPending}
                onClick={() => attempt(() => action.mutateAsync([p.id, "approve", p.version]), "PO approved.")}
              >
                <CircleCheck aria-hidden /> Approve as {p.approval_capacity}
              </GuardedButton>
            )}
            {p.status === "approved" && (
              <GuardedButton
                reason={blocking.length ? "Fix the blocking issues first." : null}
                disabled={action.isPending}
                onClick={() => attempt(() => action.mutateAsync([p.id, "issue", p.version]), "PO issued and sent to the vendor.")}
              >
                <Send aria-hidden /> Issue and send to vendor
              </GuardedButton>
            )}
            {["draft", "pending_approval", "approved"].includes(p.status) && (
              <Button
                size="sm"
                variant="ghost"
                disabled={cancel.isPending}
                onClick={() => {
                  const reason = window.prompt("Why cancel this PO?")
                  if (reason?.trim()) void attempt(() => cancel.mutateAsync([p.id, p.version, reason.trim()]), "PO cancelled.")
                }}
              >
                Cancel PO
              </Button>
            )}
          </div>
        )}
        {p.status === "pending_approval" && p.can_approve && <p className="text-xs text-muted-foreground">{p.can_approve}</p>}
        {p.status === "issued" && <Acknowledge po={p} />}
        {(p.status === "issued" || p.status === "acknowledged") && (
          <>
            <ReceiptsSection po={p} />
            <PoInvoices po={p} />
          </>
        )}
      </div>
    </AiCard>
  )
}
