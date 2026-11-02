import { useState, type FormEvent } from "react"

import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { selectClass } from "@/features/service-pod/ui"

import type { CaseDetail } from "../api"

interface MatchedLine {
  item_code: string
  order_id: string | null
  order_line_id: string | null
  billed_qty: string
  received_qty: string | null
  status: string
}

/** 3.6.2 Receiver confirms (on a phone too): what actually arrived, line by line. The
 *  confirmation posts the receipt to ERPNext. */
export function ReceiptForm({
  c,
  busy,
  onSubmit,
}: {
  c: CaseDetail
  busy: boolean
  onSubmit: (results: Record<string, Record<string, unknown>>) => void
}) {
  const matched = (c.steps.find((s) => s.key === "3.4.1")?.l5[0]?.result?.lines ?? []) as MatchedLine[]
  const waiting = matched.filter((l) => l.order_line_id && (l.status === "no_receipt" || l.status === "quantity"))
  const today = new Date().toISOString().slice(0, 10)
  const [on, setOn] = useState(today)
  const [rows, setRows] = useState(() =>
    waiting.map((l) => ({
      order_line_id: l.order_line_id!,
      item_code: l.item_code,
      received_qty: "",
      condition: "ok",
      note: "",
      expected: `${l.billed_qty} billed, ${l.received_qty ?? 0} received so far`,
    })),
  )
  const set = (i: number, patch: Partial<(typeof rows)[number]>) =>
    setRows((rs) => rs.map((r, j) => (j === i ? { ...r, ...patch } : r)))

  const submit = (e: FormEvent) => {
    e.preventDefault()
    onSubmit({
      "3.6.2.a": {
        received_on: on,
        lines: rows.map((r) => ({
          order_line_id: r.order_line_id,
          item_code: r.item_code,
          received_qty: r.received_qty || "0",
          condition: r.condition,
          ...(r.note ? { note: r.note } : {}),
        })),
      },
    })
  }

  return (
    <form onSubmit={submit} className="space-y-3 rounded-md border border-border/70 bg-background/70 p-3">
      <p className="text-xs font-semibold text-muted-foreground">3.6.2.a · Posts receipt on mobile</p>
      <label className="block space-y-1 text-sm">
        <span className="font-medium">Received on</span>
        <Input type="date" value={on} max={today} onChange={(e) => setOn(e.target.value)} required />
      </label>
      {rows.map((r, i) => (
        <fieldset key={r.order_line_id} className="space-y-2 rounded border border-border/60 p-2">
          <legend className="px-1 text-sm font-medium">{r.item_code}</legend>
          <p className="text-xs text-muted-foreground">{r.expected}</p>
          <div className="grid grid-cols-2 gap-2">
            <Input aria-label={`Quantity received of ${r.item_code}`} type="number" inputMode="decimal" min="0" step="any"
              placeholder="Quantity received now" value={r.received_qty} onChange={(e) => set(i, { received_qty: e.target.value })} required />
            <select aria-label="Condition" className={selectClass} value={r.condition} onChange={(e) => set(i, { condition: e.target.value })}>
              <option value="ok">In good condition</option>
              <option value="damaged">Damaged</option>
              <option value="short">Short</option>
            </select>
          </div>
          {r.condition !== "ok" && (
            <Input aria-label="What was wrong" placeholder="What was wrong" value={r.note} onChange={(e) => set(i, { note: e.target.value })} required />
          )}
        </fieldset>
      ))}
      <Button type="submit" size="sm" className="w-full sm:w-auto" disabled={busy || rows.length === 0}>
        Confirm the receipt
      </Button>
    </form>
  )
}
