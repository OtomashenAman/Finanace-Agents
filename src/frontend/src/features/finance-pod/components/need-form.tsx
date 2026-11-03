import { useState, type FormEvent } from "react"
import { Plus, Trash2 } from "lucide-react"

import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Textarea } from "@/components/ui/textarea"
import { selectClass } from "@/features/service-pod/ui"

import type { CaseDetail } from "../api"
import { useCaseCatalogue } from "../hooks"

interface Line {
  item_code: string
  quantity: string
  estimated_unit_price: string
}

/** 1.1.1 Describe the need: catalogue items, quantity, purpose, when, the coding the
 *  requester knows (the agent suggests the rest), and the quote if there is one. */
export function NeedForm({
  c,
  busy,
  onSubmit,
}: {
  c: CaseDetail
  busy: boolean
  onSubmit: (results: Record<string, Record<string, unknown>>) => void
}) {
  const catalogue = useCaseCatalogue(c.id)
  const quotes = c.artifacts.filter((a) => a.kind === "quote")
  // Sent back: start from what was filled in, so only what's missing needs changing
  const before = (c.steps.find((s) => s.key === "1.1.1")?.l5[0]?.previous ?? {}) as {
    purpose?: string; needed_by?: string; cost_centre_id?: string | null; lab_id?: string | null
    grant_id?: string | null; lines?: { item_code: string; quantity: string; estimated_unit_price?: string | null }[]
  }
  const [purpose, setPurpose] = useState(before.purpose ?? "")
  const [neededBy, setNeededBy] = useState(before.needed_by ?? "")
  const [costCentre, setCostCentre] = useState(before.cost_centre_id ?? "")
  const [lab, setLab] = useState(before.lab_id ?? "")
  const [grant, setGrant] = useState(before.grant_id ?? "")
  const [quote, setQuote] = useState("")
  const [lines, setLines] = useState<Line[]>(
    before.lines?.length
      ? before.lines.map((l) => ({ item_code: l.item_code, quantity: String(l.quantity), estimated_unit_price: l.estimated_unit_price ?? "" }))
      : [{ item_code: "", quantity: "1", estimated_unit_price: "" }],
  )
  const setLine = (i: number, patch: Partial<Line>) => setLines((ls) => ls.map((l, j) => (j === i ? { ...l, ...patch } : l)))
  const data = catalogue.data

  const submit = (e: FormEvent) => {
    e.preventDefault()
    onSubmit({
      "1.1.1.a": {
        channel: "form",
        purpose,
        needed_by: neededBy,
        lines: lines
          .filter((l) => l.item_code)
          .map((l) => ({
            item_code: l.item_code,
            quantity: l.quantity,
            ...(l.estimated_unit_price ? { estimated_unit_price: l.estimated_unit_price } : {}),
          })),
        cost_centre_id: costCentre || null,
        lab_id: lab || null,
        grant_id: grant || null,
      },
      "1.1.1.b": quote ? { document_id: quote } : { none_available: true },
    })
  }

  return (
    <form onSubmit={submit} className="space-y-3 rounded-md border border-border/70 bg-background/70 p-3">
      <p className="text-xs font-semibold text-muted-foreground">1.1.1.a · Item, quantity, purpose in form or chat</p>
      {lines.map((l, i) => (
        <div key={i} className="grid gap-2 sm:grid-cols-[minmax(0,1fr)_100px_130px_auto]">
          <select
            aria-label="Catalogue item"
            className={selectClass}
            value={l.item_code}
            onChange={(e) => setLine(i, { item_code: e.target.value })}
            required
          >
            <option value="">Choose an item…</option>
            {data?.items.map((item) => (
              <option key={item.code} value={item.code}>
                {item.name} ({item.code}){item.catalogue_rate ? ` · ${data.currency} ${item.catalogue_rate}` : ""}
              </option>
            ))}
          </select>
          <Input aria-label="Quantity" type="number" min="0.0001" step="any" value={l.quantity}
            onChange={(e) => setLine(i, { quantity: e.target.value })} required />
          <Input aria-label="Your estimate per unit" placeholder="Estimate / unit" type="number" min="0" step="any"
            value={l.estimated_unit_price} onChange={(e) => setLine(i, { estimated_unit_price: e.target.value })} />
          <Button type="button" variant="ghost" size="icon" aria-label="Remove line" disabled={lines.length === 1}
            onClick={() => setLines((ls) => ls.filter((_, j) => j !== i))}>
            <Trash2 className="size-4" aria-hidden />
          </Button>
        </div>
      ))}
      <Button type="button" variant="outline" size="sm"
        onClick={() => setLines((ls) => [...ls, { item_code: "", quantity: "1", estimated_unit_price: "" }])}>
        <Plus className="size-4" aria-hidden /> Add a line
      </Button>
      <label className="block space-y-1 text-sm">
        <span className="font-medium">What it's for *</span>
        <Textarea rows={2} value={purpose} onChange={(e) => setPurpose(e.target.value)} required minLength={3} />
      </label>
      <div className="grid gap-2 sm:grid-cols-4">
        <label className="space-y-1 text-sm">
          <span className="font-medium">Needed by *</span>
          <Input type="date" value={neededBy} onChange={(e) => setNeededBy(e.target.value)} required />
        </label>
        {(
          [
            ["Cost centre", costCentre, setCostCentre, data?.cost_centres],
            ["Lab", lab, setLab, data?.labs],
            ["Grant", grant, setGrant, data?.grants],
          ] as const
        ).map(([name, value, set, options]) => (
          <label key={name} className="space-y-1 text-sm">
            <span className="font-medium">{name}</span>
            <select className={selectClass} value={value} onChange={(e) => set(e.target.value)}>
              <option value="">{name === "Grant" ? "No grant" : "Let the agent suggest"}</option>
              {options?.map((o) => (
                <option key={o.id} value={o.id}>
                  {o.name}
                  {o.detail ? ` (${o.detail})` : ""}
                </option>
              ))}
            </select>
          </label>
        ))}
      </div>
      <p className="pt-1 text-xs font-semibold text-muted-foreground">1.1.1.b · Upload quote if available</p>
      <select aria-label="Quote" className={selectClass} value={quote} onChange={(e) => setQuote(e.target.value)}>
        <option value="">No quote available</option>
        {quotes.map((q) => (
          <option key={q.id} value={q.id}>
            {q.filename}
          </option>
        ))}
      </select>
      <p className="text-xs text-muted-foreground">Upload a quote under Documents (kind: Quote) to attach it here.</p>
      <Button type="submit" size="sm" disabled={busy}>
        Submit the request
      </Button>
    </form>
  )
}
