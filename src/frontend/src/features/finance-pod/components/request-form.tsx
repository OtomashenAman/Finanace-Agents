import { useState, type FormEvent } from "react"
import { Plus, Sparkles, Trash2 } from "lucide-react"
import { toast } from "sonner"

import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Textarea } from "@/components/ui/textarea"
import { AiBadge, AiCard, Field } from "@/features/service-pod/components/bits"
import { selectClass } from "@/features/service-pod/ui"
import { errorMessage } from "@/lib/api"

import { fpodApi, type LineIn, type Reference, type RequestIn } from "../api"
import { money } from "../labels"
import { EMPTY_LINE, emptyRequest } from "../request-draft"

/** 1.1.1.a in chat: free text the request agent turns into the form (nothing saved). */
export function DescribeNeed({ onDraft }: { onDraft: (draft: RequestIn, notes: string[]) => void }) {
  const [text, setText] = useState("")
  const [busy, setBusy] = useState(false)
  const run = async () => {
    setBusy(true)
    try {
      const d = await fpodApi.draftFromText(text)
      onDraft(
        {
          ...emptyRequest(),
          title: d.title,
          purpose: d.purpose,
          needed_by: d.needed_by,
          lines: d.lines.map((l) => ({ ...EMPTY_LINE, ...l })),
          source_text: text,
        },
        d.notes,
      )
      toast.success("The request agent filled the form. Check it before saving.")
    } catch (error) {
      toast.error(errorMessage(error, "The request agent couldn't read that. Fill the form instead."))
    } finally {
      setBusy(false)
    }
  }
  return (
    <AiCard
      title="Describe it in your own words"
      hint="The request agent fills the form from your text. It never invents prices or quantities: anything not in your text is left for you."
      badge={<AiBadge label="Request agent" />}
    >
      <Textarea
        rows={3}
        value={text}
        onChange={(e) => setText(e.target.value)}
        placeholder="e.g. Need 10 boxes of 200ul pipette tips at $42.50 for the sequencing study by the end of the month"
        aria-label="Describe what you need"
      />
      <div className="mt-2 flex justify-end">
        <Button size="sm" variant="outline" onClick={run} disabled={busy || text.trim().length < 5}>
          <Sparkles aria-hidden /> {busy ? "Reading…" : "Fill the form"}
        </Button>
      </div>
    </AiCard>
  )
}

function CodeSelect({
  label,
  value,
  options,
  onChange,
  hint,
}: {
  label: string
  value: string | null
  options: { code: string; name: string }[]
  onChange: (value: string | null) => void
  hint?: string
}) {
  return (
    <Field label={label} hint={hint}>
      <select className={selectClass} value={value ?? ""} onChange={(e) => onChange(e.target.value || null)}>
        <option value="">None</option>
        {value && !options.some((o) => o.code === value) && <option value={value}>{value} (not in the list)</option>}
        {options.map((o) => (
          <option key={o.code} value={o.code}>
            {o.code} · {o.name}
          </option>
        ))}
      </select>
    </Field>
  )
}

export function RequestForm({
  initial,
  reference,
  currency,
  saving,
  submitLabel,
  onSubmit,
  onCancel,
}: {
  initial: RequestIn
  reference: Reference | undefined
  currency: string
  saving: boolean
  submitLabel: string
  onSubmit: (body: RequestIn) => void
  onCancel?: () => void
}) {
  const [form, setForm] = useState<RequestIn>(initial)
  const set = <K extends keyof RequestIn>(key: K, value: RequestIn[K]) => setForm((f) => ({ ...f, [key]: value }))
  const setLine = (i: number, patch: Partial<LineIn>) =>
    setForm((f) => ({ ...f, lines: f.lines.map((l, n) => (n === i ? { ...l, ...patch } : l)) }))

  const active = <T extends { active: boolean }>(rows: T[] | undefined) => (rows ?? []).filter((r) => r.active)
  const labs = active(reference?.labs).filter((l) => !form.cost_centre_code || !l.cost_centre_code || l.cost_centre_code === form.cost_centre_code)
  const projects = active(reference?.projects).filter(
    (p) => !form.cost_centre_code || !p.cost_centre_code || p.cost_centre_code === form.cost_centre_code,
  )
  const categories = [
    ...new Set([
      ...(reference?.catalogue ?? []).map((c) => c.category),
      ...(reference?.budgets ?? []).map((b) => b.category),
    ]),
  ].filter((c): c is string => Boolean(c))
  const total = form.lines.reduce((sum, l) => sum + Number(l.quantity || 0) * Number(l.unit_price || 0), 0)

  const submit = (e: FormEvent) => {
    e.preventDefault()
    onSubmit({
      ...form,
      lines: form.lines
        .filter((l) => l.description.trim())
        .map((l) => ({ ...l, unit_price: l.unit_price === "" ? null : l.unit_price, unit: l.unit || null })),
    })
  }

  return (
    <form onSubmit={submit} className="space-y-5">
      <div className="grid gap-4 md:grid-cols-2">
        <Field label="What do you need?">
          <Input required maxLength={200} value={form.title} onChange={(e) => set("title", e.target.value)} />
        </Field>
        <Field label="Needed by">
          <Input type="date" value={form.needed_by ?? ""} onChange={(e) => set("needed_by", e.target.value || null)} />
        </Field>
        <div className="md:col-span-2">
          <Field label="What is it for?" hint="The budget and grant checks read this.">
            <Textarea rows={2} maxLength={4000} value={form.purpose} onChange={(e) => set("purpose", e.target.value)} />
          </Field>
        </div>
      </div>

      <fieldset className="space-y-2">
        <legend className="text-sm font-semibold text-brand-navy">Items and services</legend>
        <datalist id="fpod-categories">
          {categories.map((c) => (
            <option key={c} value={c} />
          ))}
        </datalist>
        <div className="overflow-x-auto">
          <table className="w-full min-w-[720px] text-sm">
            <thead className="text-left text-xs text-muted-foreground">
              <tr>
                <th className="pb-1 font-medium">Description</th>
                <th className="w-24 pb-1 font-medium">Quantity</th>
                <th className="w-24 pb-1 font-medium">Unit</th>
                <th className="w-32 pb-1 font-medium">Unit price (est.)</th>
                <th className="w-40 pb-1 font-medium">Category</th>
                <th className="w-28 pb-1 text-right font-medium">Amount</th>
                <th className="w-10" />
              </tr>
            </thead>
            <tbody>
              {form.lines.map((l, i) => (
                <tr key={i}>
                  <td className="py-1 pr-2">
                    <Input
                      aria-label={`Line ${i + 1} description`}
                      value={l.description}
                      maxLength={500}
                      onChange={(e) => setLine(i, { description: e.target.value })}
                    />
                  </td>
                  <td className="py-1 pr-2">
                    <Input
                      aria-label={`Line ${i + 1} quantity`}
                      inputMode="decimal"
                      value={l.quantity}
                      onChange={(e) => setLine(i, { quantity: e.target.value })}
                    />
                  </td>
                  <td className="py-1 pr-2">
                    <Input
                      aria-label={`Line ${i + 1} unit`}
                      value={l.unit ?? ""}
                      maxLength={20}
                      onChange={(e) => setLine(i, { unit: e.target.value || null })}
                    />
                  </td>
                  <td className="py-1 pr-2">
                    <Input
                      aria-label={`Line ${i + 1} unit price`}
                      inputMode="decimal"
                      value={l.unit_price ?? ""}
                      onChange={(e) => setLine(i, { unit_price: e.target.value || null })}
                    />
                  </td>
                  <td className="py-1 pr-2">
                    <Input
                      aria-label={`Line ${i + 1} category`}
                      list="fpod-categories"
                      value={l.category ?? ""}
                      maxLength={64}
                      onChange={(e) => setLine(i, { category: e.target.value || null })}
                    />
                  </td>
                  <td className="py-1 pr-2 text-right tabular-nums">
                    {l.unit_price ? money(Number(l.quantity || 0) * Number(l.unit_price)) : "—"}
                  </td>
                  <td className="py-1">
                    <Button
                      type="button"
                      variant="ghost"
                      size="icon"
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
        </div>
        <div className="flex items-center justify-between">
          <Button
            type="button"
            variant="outline"
            size="sm"
            onClick={() => setForm((f) => ({ ...f, lines: [...f.lines, { ...EMPTY_LINE }] }))}
          >
            <Plus aria-hidden /> Add line
          </Button>
          <p className="text-sm">
            Estimated total <span className="font-semibold tabular-nums">{money(total, currency)}</span>
          </p>
        </div>
      </fieldset>

      <fieldset className="space-y-2">
        <legend className="text-sm font-semibold text-brand-navy">Coding</legend>
        <p className="text-xs text-muted-foreground">
          Leave it empty if you're not sure: the request agent suggests it after you save.
        </p>
        <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
          <CodeSelect
            label="Cost centre"
            value={form.cost_centre_code}
            options={active(reference?.cost_centres)}
            onChange={(v) => set("cost_centre_code", v)}
          />
          <CodeSelect label="Lab" value={form.lab_code} options={labs} onChange={(v) => set("lab_code", v)} />
          <CodeSelect
            label="Project"
            value={form.project_code}
            options={projects}
            onChange={(v) => set("project_code", v)}
          />
          <CodeSelect
            label="Grant"
            value={form.grant_code}
            options={active(reference?.grants)}
            onChange={(v) => set("grant_code", v)}
          />
        </div>
      </fieldset>

      <div className="flex justify-end gap-2">
        {onCancel && (
          <Button type="button" variant="outline" onClick={onCancel}>
            Cancel
          </Button>
        )}
        <Button type="submit" disabled={saving}>
          {saving ? "Saving…" : submitLabel}
        </Button>
      </div>
    </form>
  )
}
