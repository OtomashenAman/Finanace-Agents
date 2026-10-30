import { useState } from "react"

import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"

import type { CaseDetail } from "../../api"
import { Card, GuardedButton, Pill } from "../../components/bits"
import { formatDateTime } from "../../labels"
import { selectClass } from "../../ui"
import { useRunAction } from "../../use-run-action"
import { money, type InvoiceState } from "../shared"
import { InvoiceTable } from "../shared-ui"

interface AllocationState {
  lines: { invoice_id: string; invoice_number: string; amount: string }[]
  source_message_id: string
  quote: string
  by: "ai" | "preparer"
}

/** Bank: the receipt, the customer's allocation and the posting (deck bank screens 1-2). */
export function BankPanel({ c }: { c: CaseDetail }) {
  const { run, pending } = useRunAction(c)
  const s = c.state as {
    receipt?: { reference: string; payer: string; date: string; amount: string; currency: string; cleared: boolean }
    customer?: { name: string }
    open_invoices?: InvoiceState[]
    currency?: string
    allocation?: AllocationState
  }
  const replies = c.messages.filter((m) => m.direction === "inbound")
  const [replyId, setReplyId] = useState("")
  const [quote, setQuote] = useState("")
  const [amounts, setAmounts] = useState<Record<string, string>>({})
  const r = s.receipt
  const total = (s.allocation?.lines ?? []).reduce((sum, l) => sum + Number(l.amount), 0)

  return (
    <Card title={r ? `${r.reference} · ${money(r.amount, r.currency)}` : "Receipt"} hint={r ? `${r.payer} · value date ${r.date} · ${r.cleared ? "cleared" : "NOT cleared"}` : undefined}>
      <p className="mb-2 text-sm">
        Customer: <strong>{s.customer?.name}</strong>
      </p>
      <InvoiceTable rows={s.open_invoices ?? []} currency={s.currency} />
      <div className="mt-4 rounded-md bg-secondary/40 p-3 text-sm">
        <p className="font-semibold text-brand-navy">Customer's allocation</p>
        {s.allocation ? (
          <>
            <ul className="mt-1">
              {s.allocation.lines.map((l) => (
                <li key={l.invoice_id} className="flex justify-between tabular-nums">
                  <span>{l.invoice_number}</span>
                  <span>{money(l.amount, s.currency)}</span>
                </li>
              ))}
            </ul>
            <p className={`mt-1 text-xs ${r && total === Number(r.amount) ? "text-emerald-800" : "text-red-800"}`}>
              Total {money(total, s.currency)} {r && (total === Number(r.amount) ? "= bank receipt" : `≠ receipt ${money(r.amount, s.currency)}`)}
            </p>
            <p className="mt-1 text-xs text-muted-foreground italic">
              “{s.allocation.quote}” ({s.allocation.by === "ai" ? "read by AI, checked" : "recorded by the preparer"})
            </p>
          </>
        ) : (
          <p className="text-xs text-muted-foreground">None yet. A matching amount never decides it: ask the customer.</p>
        )}
      </div>

      {c.allowed_actions.set_allocation === null && replies.length > 0 && (
        <form
          className="mt-3 space-y-2 border-t pt-3"
          onSubmit={(e) => {
            e.preventDefault()
            const lines = Object.entries(amounts)
              .filter(([, a]) => a.trim())
              .map(([invoice_id, amount]) => ({ invoice_id, amount }))
            void run("set_allocation", { lines, source_message_id: replyId, quote }, "Allocation recorded.")
          }}
        >
          <p className="text-xs font-semibold">Record the allocation by hand (from the customer's reply)</p>
          <select className={selectClass} value={replyId} onChange={(e) => setReplyId(e.target.value)} aria-label="Reply">
            <option value="">From which reply…</option>
            {replies.map((m) => (
              <option key={m.id} value={m.id}>
                {m.from_email} · {formatDateTime(m.received_at)}
              </option>
            ))}
          </select>
          <Input placeholder="The customer's exact words" value={quote} onChange={(e) => setQuote(e.target.value)} />
          {(s.open_invoices ?? []).map((inv) => (
            <label key={inv.id} className="flex items-center gap-2 text-xs">
              <span className="w-24">{inv.number}</span>
              <Input
                className="h-9 max-w-[160px]"
                inputMode="decimal"
                placeholder="Amount"
                value={amounts[inv.id] ?? ""}
                onChange={(e) => setAmounts({ ...amounts, [inv.id]: e.target.value })}
              />
            </label>
          ))}
          <Button type="submit" size="sm" variant="outline" disabled={pending || !replyId || quote.trim().length < 3}>
            Record allocation
          </Button>
        </form>
      )}

      <div className="mt-3 flex flex-wrap items-center gap-2 border-t pt-3">
        <GuardedButton
          reason={c.allowed_actions.create_posting_task}
          disabled={pending}
          onClick={() => void run("create_posting_task", {}, "Manual Receive Payment queued for the Finance Admin.")}
        >
          Queue manual QuickBooks posting
        </GuardedButton>
        {c.posting_tasks.map((t) => (
          <Pill key={t.id} label={`Posting: ${t.status.replace("_", " ")}`} tone={t.status === "verified" ? "good" : "info"} />
        ))}
      </div>
    </Card>
  )
}
