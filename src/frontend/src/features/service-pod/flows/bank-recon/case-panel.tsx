import { useState } from "react"
import { Link } from "react-router"

import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { cn } from "@/lib/utils"

import type { CaseDetail } from "../../api"
import { Card, GuardedButton, Pill } from "../../components/bits"
import { TaskActions } from "../../components/task-actions"
import { CASE_STATUS, formatDateTime, MESSAGE_STATUS, TASK_STATUS } from "../../labels"
import { selectClass } from "../../ui"
import { useRunAction } from "../../use-run-action"
import { money, type InvoiceState } from "../shared"
import { CheckRow, InvoiceTable } from "../shared-ui"

interface BankState {
  receipt?: {
    reference: string
    payer: string
    date: string
    amount: string
    currency: string
    cleared: boolean
    proof_reference: string | null
  }
  customer?: { name: string }
  open_invoices?: InvoiceState[]
  currency?: string
  allocation?: {
    lines: { invoice_id: string; invoice_number: string; amount: string }[]
    source_message_id: string
    quote: string
    by: "ai" | "hand"
  }
}

function view(c: CaseDetail) {
  const s = c.state as BankState
  const r = s.receipt
  const total = (s.allocation?.lines ?? []).reduce((sum, l) => sum + Number(l.amount), 0)
  const task = c.posting_tasks.find((t) => t.kind === "receive_payment")
  const variance = r && s.allocation ? Number(r.amount) - total : null
  return { s, r, total, task, variance }
}

/** Deck bank screen 1-2 header: the receipt, its status chips, the customer's open invoices. */
export function BankReceipt({ c }: { c: CaseDetail }) {
  const { s, r, task, variance } = view(c)
  return (
    <Card
      title={r ? `${r.reference} · ${money(r.amount, r.currency)}` : "Receipt"}
      hint={r ? `${r.payer} · value date ${r.date} · ${r.cleared ? "cleared" : "NOT cleared"}` : undefined}
    >
      <p className="mb-3 flex flex-wrap gap-1.5">
        <Pill label={`Bank cleared: ${r?.cleared ? "yes" : "no"}`} tone={r?.cleared ? "good" : "bad"} />
        <Pill
          label={variance === null ? "Variance: no allocation yet" : `Variance: ${money(variance, s.currency)}`}
          tone={variance === null ? "neutral" : variance === 0 ? "good" : "bad"}
        />
        <Pill label={`Posting: ${task ? TASK_STATUS[task.status][0].toLowerCase() : "not queued"}`} tone={task?.status === "verified" ? "good" : "info"} />
        <Pill label="App writes to QuickBooks: 0" tone="neutral" />
      </p>
      <p className="mb-2 text-sm">
        Customer: <strong>{s.customer?.name}</strong>
        {r?.proof_reference && <span className="ml-2 text-xs text-muted-foreground">Bank proof: {r.proof_reference}</span>}
      </p>
      <InvoiceTable rows={s.open_invoices ?? []} currency={s.currency} />
    </Card>
  )
}

/** Deck bank screen 2 (left): the customer's allocation, read from the reply or recorded by
 *  hand from it, and whether it settles the receipt exactly. */
export function BankAllocation({ c }: { c: CaseDetail }) {
  const { run, pending } = useRunAction(c)
  const { s, r, total } = view(c)
  const replies = c.messages.filter((m) => m.direction === "inbound")
  const [replyId, setReplyId] = useState("")
  const [quote, setQuote] = useState("")
  const [amounts, setAmounts] = useState<Record<string, string>>({})
  const invoices = s.open_invoices ?? []
  // The same checks the server makes, as the amounts are typed
  const entered = invoices.filter((inv) => (amounts[inv.id] ?? "").trim())
  const lineProblem = (inv: InvoiceState) => {
    const raw = (amounts[inv.id] ?? "").trim()
    if (!raw) return null
    const n = Number(raw)
    if (!Number.isFinite(n) || n <= 0) return "must be above 0"
    if (n > Number(inv.balance)) return `above the open ${money(inv.balance, s.currency)}`
    return null
  }
  const typed = entered.reduce((t, inv) => t + (Number(amounts[inv.id]) || 0), 0)
  const receipt = Number(r?.amount ?? 0)
  const balanced = Math.abs(typed - receipt) < 0.005
  const valid = entered.length > 0 && balanced && entered.every((inv) => lineProblem(inv) === null)
  return (
    <Card title="Customer's allocation" hint="A matching amount never decides it: the customer says which invoices, in their own words.">
      {s.allocation ? (
        <>
          <ul>
            {s.allocation.lines.map((l) => (
              <li key={l.invoice_id} className="flex justify-between text-sm tabular-nums">
                <span>{l.invoice_number}</span>
                <span>{money(l.amount, s.currency)}</span>
              </li>
            ))}
          </ul>
          <p className={`mt-1 text-xs ${r && total === Number(r.amount) ? "text-emerald-800" : "text-red-800"}`}>
            Total {money(total, s.currency)} {r && (total === Number(r.amount) ? "= bank receipt" : `≠ receipt ${money(r.amount, s.currency)}`)}
          </p>
          <p className="mt-1 text-xs text-muted-foreground italic">
            “{s.allocation.quote}” ({s.allocation.by === "ai" ? "read by AI, checked" : "recorded by hand"})
          </p>
        </>
      ) : (
        <p className="text-xs text-muted-foreground">None yet: import the customer's reply.</p>
      )}

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
          {invoices.map((inv) => {
            const problem = lineProblem(inv)
            return (
              <label key={inv.id} className="flex flex-wrap items-center gap-2 text-xs">
                <span className="w-24">{inv.number}</span>
                <Input
                  className={cn("h-9 max-w-[160px]", problem && "border-red-500")}
                  inputMode="decimal"
                  placeholder={`up to ${money(inv.balance, s.currency)}`}
                  value={amounts[inv.id] ?? ""}
                  onChange={(e) => setAmounts({ ...amounts, [inv.id]: e.target.value })}
                />
                {problem && <span className="text-red-800">{problem}</span>}
              </label>
            )
          })}
          {entered.length > 0 && (
            <p className={cn("text-xs tabular-nums", balanced ? "text-emerald-800" : "text-red-800")}>
              {entered.map((inv) => money(amounts[inv.id], s.currency)).join(" + ")} = {money(typed, s.currency)}{" "}
              {balanced ? "= receipt ✓" : `≠ receipt ${money(receipt, s.currency)} (${typed < receipt ? "short" : "over"} ${money(Math.abs(receipt - typed), s.currency)})`}
            </p>
          )}
          <Button type="submit" size="sm" variant="outline" disabled={pending || !replyId || quote.trim().length < 3 || !valid}>
            Record allocation
          </Button>
        </form>
      )}
    </Card>
  )
}

/** Deck bank screen 2 (right): posting control, from the duplicate check to verification. */
const LIFECYCLE = [
  ["proposed", "To post"],
  ["recorded_unverified", "Recorded"],
  ["verified", "Verified"],
] as const

/** to post → recorded (txn) → verified, with when. */
function TaskTracker({ task }: { task: NonNullable<ReturnType<typeof view>["task"]> }) {
  const at = LIFECYCLE.findIndex(([k]) => k === task.status)
  const when: Record<string, string | null> = {
    proposed: task.created_at,
    recorded_unverified: task.recorded_at,
    verified: task.verified_at,
  }
  return (
    <ol className="mb-3 flex flex-wrap items-center gap-1 text-xs">
      {LIFECYCLE.map(([key, label], i) => (
        <li key={key} className="flex items-center gap-1">
          {i > 0 && <span className="text-muted-foreground">→</span>}
          <span
            className={cn(
              "rounded-full px-2 py-0.5",
              i < at || task.status === "verified" ? "bg-emerald-100 text-emerald-900" : i === at ? "bg-primary/15 font-semibold text-primary" : "bg-secondary text-muted-foreground",
            )}
            title={when[key] ? formatDateTime(when[key]) : undefined}
          >
            {label}
            {key === "recorded_unverified" && task.external_txn_id && ` · ${task.external_txn_id}`}
          </span>
        </li>
      ))}
      {task.status === "cancelled" && <Pill label="Cancelled" tone="neutral" />}
    </ol>
  )
}

export function BankPosting({ c }: { c: CaseDetail }) {
  const { run, pending } = useRunAction(c)
  const { task } = view(c)
  const recorded = c.blockers.some((b) => b.includes("already records"))
  const ack = [...c.messages].reverse().find((m) => m.purpose === "acknowledgement")
  return (
    <Card title="Posting control" hint="The application never posts: the Finance Admin does, and a fresh export proves it.">
      {task && <TaskTracker task={task} />}
      <ul className="divide-y text-xs">
        <CheckRow state={recorded ? "failed" : "done"} label="Duplicate check">
          {recorded ? "A newer source already records this payment" : "No payment with this reference is recorded in QuickBooks"}
        </CheckRow>
        <CheckRow state={task ? (task.status === "proposed" ? "waiting" : "done") : "waiting"} label="Manual task">
          {task
            ? `Receive Payment, applied as allocated: ${TASK_STATUS[task.status][0].toLowerCase()}${task.external_txn_id ? ` (QuickBooks ${task.external_txn_id})` : ""}`
            : "Queued once the allocation is approved"}
        </CheckRow>
        <CheckRow state={task?.status === "verified" ? "done" : "waiting"} label="Re-read QuickBooks">
          {task?.status === "verified"
            ? `Verified against a fresh export ${task.verified_at ? formatDateTime(task.verified_at) : ""}`
            : "A fresh export imported after the posting must show the payment ID, date, customer, amount and the remaining balances"}
        </CheckRow>
        <CheckRow state={ack?.status === "sent" ? "done" : task?.status === "verified" ? "waiting" : "na"} label="Acknowledgement">
          {ack ? `${ack.subject}: ${MESSAGE_STATUS[ack.status][0].toLowerCase()}` : "Only after verification"}
        </CheckRow>
      </ul>
      <div className="mt-3 flex flex-wrap items-center gap-2">
        <GuardedButton
          reason={c.allowed_actions.create_posting_task}
          disabled={pending}
          onClick={() => void run("create_posting_task", {}, "Manual Receive Payment queued: post it in QuickBooks.")}
        >
          Queue manual QuickBooks posting
        </GuardedButton>
      </div>
      {task && task.status !== "verified" && task.status !== "cancelled" && <TaskActions t={task} />}
    </Card>
  )
}

/** The AR case of the same customer: the promises this cash pays. */
export function BankArLink({ c }: { c: CaseDetail }) {
  const ar = c.related_cases.filter((r) => r.workflow === "ar_collections")
  if (ar.length === 0) return null
  return (
    <Card title="Collections" hint="Once verified, this cash counts as kept against the customer's promises.">
      <ul className="divide-y text-xs">
        {ar.map((r) => (
          <li key={r.id} className="flex flex-wrap items-center gap-2 py-1.5">
            <Link to={`/pod/cases/${r.id}`} className="font-semibold text-primary hover:underline">
              {r.reference}
            </Link>
            <Pill label={CASE_STATUS[r.status][0]} tone={CASE_STATUS[r.status][1]} />
            <span className="text-muted-foreground">{r.summary}</span>
          </li>
        ))}
      </ul>
    </Card>
  )
}
