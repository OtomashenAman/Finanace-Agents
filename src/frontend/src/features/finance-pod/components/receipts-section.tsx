import { useState } from "react"
import { PackageCheck } from "lucide-react"

import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { formatDate } from "../labels"
import { attempt } from "@/features/service-pod/ui"

import { useFpodMutation, useReceipts } from "../hooks"
import { invoicesApi } from "../invoices-api"
import type { PurchaseOrder } from "../procurement-api"

/** What arrived against an issued PO (Phase 2 receipt, as far as Phase 3 needs it). */
export function ReceiptsSection({ po }: { po: PurchaseOrder }) {
  const receipts = useReceipts(po.id)
  const record = useFpodMutation(invoicesApi.recordReceipt)
  const [open, setOpen] = useState(false)
  const [qty, setQty] = useState<Record<number, string>>({})
  const [on, setOn] = useState(new Date().toISOString().slice(0, 10))
  const received: Record<number, number> = {}
  for (const r of receipts.data ?? []) {
    for (const l of r.lines) received[l.po_line] = (received[l.po_line] ?? 0) + Number(l.quantity)
  }
  return (
    <section aria-label="Receipts" className="space-y-2 rounded-lg border border-border p-3">
      <div className="flex items-center justify-between gap-2">
        <h3 className="flex items-center gap-1.5 font-semibold">
          <PackageCheck className="size-4" aria-hidden /> Receipts
        </h3>
        {!open && (
          <Button size="sm" variant="outline" onClick={() => setOpen(true)}>
            Record what arrived
          </Button>
        )}
      </div>
      <ul className="space-y-0.5 text-xs">
        {po.lines.map((l, i) => (
          <li key={i}>
            Line {i + 1}: {received[i + 1] ?? 0} of {Number(l.quantity)} {l.unit ?? ""} received
          </li>
        ))}
      </ul>
      {(receipts.data ?? []).length > 0 && (
        <p className="text-xs text-muted-foreground">
          {(receipts.data ?? [])
            .map((r) => `${formatDate(r.received_on)} (${r.via === "mobile_link" ? "receiver's phone" : "in the app"}${r.receiver_email ? `, ${r.receiver_email}` : ""})`)
            .join(" · ")}
        </p>
      )}
      {open && (
        <div className="space-y-2">
          {po.lines.map((l, i) => (
            <label key={i} className="flex items-center justify-between gap-2 text-sm">
              <span>
                {i + 1}. {l.description}
              </span>
              <Input
                className="w-24"
                inputMode="decimal"
                value={qty[i + 1] ?? String(Math.max(0, Number(l.quantity) - (received[i + 1] ?? 0)))}
                onChange={(e) => setQty({ ...qty, [i + 1]: e.target.value })}
              />
            </label>
          ))}
          <div className="flex items-center gap-2">
            <Input className="w-40" type="date" value={on} onChange={(e) => setOn(e.target.value)} />
            <Button
              size="sm"
              disabled={record.isPending}
              onClick={async () => {
                const lines = po.lines.map((l, i) => ({
                  po_line: i + 1,
                  quantity: qty[i + 1] ?? String(Math.max(0, Number(l.quantity) - (received[i + 1] ?? 0))),
                }))
                const ok = await attempt(() => record.mutateAsync([po.id, on, lines, ""]), "Receipt recorded; waiting invoices re-matched.")
                if (ok) setOpen(false)
              }}
            >
              Save receipt
            </Button>
            <Button size="sm" variant="ghost" onClick={() => setOpen(false)}>
              Cancel
            </Button>
          </div>
        </div>
      )}
    </section>
  )
}
