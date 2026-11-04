import { useState, type FormEvent } from "react"
import { Plus, Trash2 } from "lucide-react"

import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Field } from "@/features/service-pod/components/bits"
import { selectClass } from "@/features/service-pod/ui"

import { usePurchaseOrders, useReference } from "../hooks"
import type { InvoiceIn } from "../invoices-api"
import { money } from "../labels"

const EMPTY_LINE = { description: "", quantity: "1", unit_price: "", po_line: null }

/** The invoice's data, as AP confirms it. */
export function InvoiceForm({
  initial,
  saving,
  submitLabel,
  onSubmit,
  extra,
}: {
  initial: InvoiceIn
  saving: boolean
  submitLabel: string
  onSubmit: (body: InvoiceIn) => void
  extra?: React.ReactNode
}) {
  const reference = useReference()
  const pos = usePurchaseOrders(null)
  const [form, setForm] = useState<InvoiceIn>(initial)
  const set = <K extends keyof InvoiceIn>(k: K, v: InvoiceIn[K]) => setForm((f) => ({ ...f, [k]: v }))
  const vendors = (reference.data?.vendors ?? []).filter((v) => v.status === "approved")
  const livePos = (pos.data ?? []).filter(
    (p) => (p.status === "issued" || p.status === "acknowledged") && (!form.vendor_code || p.vendor_name === vendors.find((v) => v.code === form.vendor_code)?.name),
  )
  const linesTotal = form.lines.reduce((s, l) => s + Number(l.quantity || 0) * Number(l.unit_price || 0), 0)
  const expected = linesTotal + Number(form.tax_total || 0)
  const off = form.total !== null && form.total !== "" && Math.abs(expected - Number(form.total)) > 0.005

  const submit = (e: FormEvent) => {
    e.preventDefault()
    onSubmit({
      ...form,
      lines: form.lines.filter((l) => l.description.trim()),
      total: form.total || null,
      tax_total: form.tax_total || "0",
    })
  }

  return (
    <form onSubmit={submit} className="space-y-4 text-sm">
      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <Field label="Vendor (vendor master)">
          <select className={selectClass} value={form.vendor_code ?? ""} onChange={(e) => set("vendor_code", e.target.value || null)}>
            <option value="">Choose…</option>
            {vendors.map((v) => (
              <option key={v.code} value={v.code}>
                {v.name} ({v.code})
              </option>
            ))}
          </select>
        </Field>
        <Field label="Vendor's invoice number">
          <Input value={form.vendor_invoice_number ?? ""} onChange={(e) => set("vendor_invoice_number", e.target.value || null)} />
        </Field>
        <Field label="Invoice date">
          <Input type="date" value={form.invoice_date ?? ""} onChange={(e) => set("invoice_date", e.target.value || null)} />
        </Field>
        <Field label="Due date">
          <Input type="date" value={form.due_date ?? ""} onChange={(e) => set("due_date", e.target.value || null)} />
        </Field>
        <Field label="Our PO">
          <Input list="fpod-live-pos" value={form.po_reference ?? ""} onChange={(e) => set("po_reference", e.target.value || null)} placeholder="PO-00001" />
          <datalist id="fpod-live-pos">
            {livePos.map((p) => (
              <option key={p.id} value={p.reference}>
                {p.vendor_name} · {money(p.total, p.currency)}
              </option>
            ))}
          </datalist>
        </Field>
        <Field label="Currency">
          <Input maxLength={3} value={form.currency} onChange={(e) => set("currency", e.target.value.toUpperCase())} />
        </Field>
        <Field label="Tax">
          <Input inputMode="decimal" value={form.tax_total} onChange={(e) => set("tax_total", e.target.value)} />
        </Field>
        <Field label="Invoice total (incl. tax)">
          <Input inputMode="decimal" value={form.total ?? ""} onChange={(e) => set("total", e.target.value || null)} />
        </Field>
      </div>

      <fieldset className="space-y-2">
        <legend className="font-semibold text-brand-navy">Lines</legend>
        <table className="w-full min-w-[620px]">
          <thead className="text-left text-xs text-muted-foreground">
            <tr>
              <th className="pb-1 font-medium">Description</th>
              <th className="w-24 pb-1 font-medium">Qty</th>
              <th className="w-28 pb-1 font-medium">Unit price</th>
              <th className="w-24 pb-1 font-medium">PO line</th>
              <th className="w-28 pb-1 text-right font-medium">Amount</th>
              <th className="w-10" />
            </tr>
          </thead>
          <tbody>
            {form.lines.map((l, i) => (
              <tr key={i}>
                {(["description", "quantity", "unit_price"] as const).map((k) => (
                  <td key={k} className="py-1 pr-2">
                    <Input
                      aria-label={`Line ${i + 1} ${k}`}
                      inputMode={k === "description" ? undefined : "decimal"}
                      value={l[k]}
                      onChange={(e) =>
                        setForm((f) => ({ ...f, lines: f.lines.map((x, n) => (n === i ? { ...x, [k]: e.target.value } : x)) }))
                      }
                    />
                  </td>
                ))}
                <td className="py-1 pr-2">
                  <Input
                    aria-label={`Line ${i + 1} PO line`}
                    type="number"
                    min={1}
                    placeholder="auto"
                    value={l.po_line ?? ""}
                    onChange={(e) =>
                      setForm((f) => ({
                        ...f,
                        lines: f.lines.map((x, n) => (n === i ? { ...x, po_line: e.target.value ? Number(e.target.value) : null } : x)),
                      }))
                    }
                  />
                </td>
                <td className="py-1 pr-2 text-right tabular-nums">{money(Number(l.quantity || 0) * Number(l.unit_price || 0))}</td>
                <td>
                  <Button
                    type="button"
                    size="icon"
                    variant="ghost"
                    aria-label={`Remove line ${i + 1}`}
                    onClick={() => setForm((f) => ({ ...f, lines: f.lines.filter((_, n) => n !== i) }))}
                  >
                    <Trash2 aria-hidden />
                  </Button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        <div className="flex flex-wrap items-center justify-between gap-2">
          <Button type="button" size="sm" variant="outline" onClick={() => setForm((f) => ({ ...f, lines: [...f.lines, { ...EMPTY_LINE }] }))}>
            <Plus aria-hidden /> Add line
          </Button>
          <p className={off ? "text-amber-800" : "text-muted-foreground"}>
            Lines {money(linesTotal)} + tax {money(form.tax_total || 0)} = {money(expected)}
            {off && ` · the invoice total says ${money(form.total)}`}
          </p>
        </div>
      </fieldset>
      <div className="flex flex-wrap gap-2">
        <Button type="submit" disabled={saving}>
          {saving ? "Saving…" : submitLabel}
        </Button>
        {extra}
      </div>
    </form>
  )
}
