import { useState } from "react"
import { useParams } from "react-router"
import { useQuery } from "@tanstack/react-query"
import { PackageCheck } from "lucide-react"

import { Alert } from "@/components/ui/alert"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { errorMessage } from "@/lib/api"

import { invoicesApi } from "./invoices-api"

/** The receiver's phone: confirm what arrived. No login: the single-use link is the key. */
export function ReceiptConfirmPage() {
  const { token = "" } = useParams()
  const view = useQuery({ queryKey: ["receipt", token], queryFn: () => invoicesApi.receiptView(token), retry: false })
  const [qty, setQty] = useState<Record<number, string>>({})
  const [on, setOn] = useState(new Date().toISOString().slice(0, 10))
  const [notes, setNotes] = useState("")
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [done, setDone] = useState(false)

  const submit = async () => {
    if (!view.data) return
    setBusy(true)
    setError(null)
    try {
      const lines = view.data.lines.map((l) => ({
        po_line: l.position,
        quantity: qty[l.position] ?? String(Math.max(0, Number(l.ordered) - Number(l.received))),
      }))
      await invoicesApi.confirmReceipt(token, on, lines, notes)
      setDone(true)
    } catch (err) {
      setError(errorMessage(err, "That didn't go through. Check the quantities and try again."))
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="min-h-svh bg-brand-page px-3 py-6">
      <div className="mx-auto max-w-md rounded-2xl border border-border bg-card p-5 shadow-sm">
        <p className="flex items-center gap-2 text-xs font-medium text-muted-foreground">
          <PackageCheck className="size-4" aria-hidden /> Confirm a delivery
        </p>
        {view.isPending ? (
          <p className="mt-4 text-sm">Loading…</p>
        ) : view.isError ? (
          <Alert className="mt-4">{errorMessage(view.error, "This link isn't valid any more.")}</Alert>
        ) : done || view.data.status === "used" ? (
          <div className="mt-4 space-y-2">
            <h1 className="text-xl font-semibold">Thank you</h1>
            <p className="text-sm">Your confirmation is recorded; the invoice is matched again automatically.</p>
          </div>
        ) : view.data.status === "expired" ? (
          <Alert className="mt-4">This link has expired.</Alert>
        ) : (
          <div className="mt-3 space-y-4">
            <div>
              <h1 className="text-lg font-semibold">
                {view.data.po_reference} · {view.data.vendor_name}
              </h1>
              <p className="text-sm text-muted-foreground">
                {view.data.receiver_name ? `${view.data.receiver_name}, w` : "W"}hat arrived? The invoice
                {view.data.invoice_reference ? ` ${view.data.invoice_reference}` : ""} waits for this.
              </p>
            </div>
            <ul className="space-y-3">
              {view.data.lines.map((l) => {
                const left = Math.max(0, Number(l.ordered) - Number(l.received))
                return (
                  <li key={l.position} className="rounded-xl border border-border p-3">
                    <p className="font-medium">{l.description}</p>
                    <p className="text-xs text-muted-foreground">
                      Ordered {Number(l.ordered)} {l.unit ?? ""} · already received {Number(l.received)}
                    </p>
                    <label className="mt-2 flex items-center justify-between gap-3 text-sm">
                      Received now
                      <Input
                        className="h-12 w-28 text-center text-lg"
                        inputMode="decimal"
                        value={qty[l.position] ?? String(left)}
                        onChange={(e) => setQty({ ...qty, [l.position]: e.target.value })}
                      />
                    </label>
                  </li>
                )
              })}
            </ul>
            <label className="block text-sm">
              Date received
              <Input className="mt-1 h-11" type="date" value={on} onChange={(e) => setOn(e.target.value)} />
            </label>
            <Input value={notes} onChange={(e) => setNotes(e.target.value)} placeholder="Notes (damaged, partial…)" className="h-11" />
            {error && <Alert>{error}</Alert>}
            <Button className="h-12 w-full text-base" disabled={busy} onClick={() => void submit()}>
              {busy ? "Sending…" : "Confirm receipt"}
            </Button>
          </div>
        )}
      </div>
    </div>
  )
}
