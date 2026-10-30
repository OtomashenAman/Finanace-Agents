import { useState } from "react"

import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { useCurrentUser } from "@/features/auth/hooks"

import type { CaseDetail, ReviewTaskKind } from "../api"
import { useSnapshotRows } from "../hooks"
import { useRunAction } from "../use-run-action"
import { formatDateTime, REVIEW_KIND } from "../labels"
import { Card, Empty, GuardedButton, Pill } from "./bits"
import { selectClass } from "../ui"

export function ReviewTasks({ c }: { c: CaseDetail }) {
  const { run, pending } = useRunAction(c)
  const [kind, setKind] = useState<ReviewTaskKind>("ambiguity")
  const [subject, setSubject] = useState("")
  const [detail, setDetail] = useState("")
  const [blocking, setBlocking] = useState(true)
  const [resolving, setResolving] = useState<Record<string, string>>({})
  const reason = c.allowed_actions.add_review_task

  return (
    <Card
      title="Review tasks"
      hint="Unknown dates, disputes and missing documents are never assumed away: a person settles each one."
    >
      {c.review_tasks.length === 0 && <Empty>None raised.</Empty>}
      <ul className="divide-y">
        {c.review_tasks.map((t) => (
          <li key={t.id} className="py-3 text-sm">
            <p className="flex flex-wrap items-center gap-2">
              <Pill label={REVIEW_KIND[t.kind]} tone={t.status === "open" ? (t.blocking ? "warn" : "info") : "good"} />
              {t.subject && <span className="font-semibold">{t.subject}</span>}
              {t.blocking && t.status === "open" && <span className="text-xs text-amber-800">blocks approval</span>}
            </p>
            <p className="mt-1">{t.detail}</p>
            <p className="text-xs text-muted-foreground">
              Raised by {t.created_by ?? "the system"} · {formatDateTime(t.created_at)}
            </p>
            {t.status === "resolved" ? (
              <p className="mt-1 text-xs">
                Resolved by {t.resolved_by}: <span className="italic">{t.resolution}</span>
              </p>
            ) : t.requirement ? (
              <p className="mt-1 text-xs text-amber-800">
                {t.requirement.type === "customer_date"
                  ? "Settles only when the customer's reply gives the date."
                  : `Settles when an approved ${t.requirement.kind?.replace("_", " ")} for ${t.requirement.invoice ?? "the case"} is added.`}
              </p>
            ) : (
              reason === null && (
                <div className="mt-2 flex gap-2">
                  <Input
                    placeholder="How it was resolved (the evidence)"
                    value={resolving[t.id] ?? ""}
                    onChange={(e) => setResolving({ ...resolving, [t.id]: e.target.value })}
                  />
                  <Button
                    size="sm"
                    variant="outline"
                    disabled={pending || (resolving[t.id] ?? "").trim().length < 5}
                    onClick={() =>
                      void run("resolve_review_task", { task_id: t.id, resolution: resolving[t.id] }, "Resolved.")
                    }
                  >
                    Resolve
                  </Button>
                </div>
              )
            )}
          </li>
        ))}
      </ul>
      {reason === null && (
        <form
          className="mt-3 grid gap-2 border-t pt-3 sm:grid-cols-[160px_160px_1fr]"
          onSubmit={(e) => {
            e.preventDefault()
            void run("add_review_task", { kind, subject: subject || null, detail, blocking }, "Review task raised.").then(
              (r) => {
                if (r) {
                  setDetail("")
                  setSubject("")
                }
              },
            )
          }}
        >
          <select className={selectClass} value={kind} onChange={(e) => setKind(e.target.value as ReviewTaskKind)} aria-label="Kind">
            {Object.entries(REVIEW_KIND).map(([k, v]) => (
              <option key={k} value={k}>
                {v}
              </option>
            ))}
          </select>
          <Input placeholder="Subject (e.g. INV-101)" value={subject} onChange={(e) => setSubject(e.target.value)} />
          <Input placeholder="What needs settling" value={detail} onChange={(e) => setDetail(e.target.value)} />
          <label className="flex items-center gap-2 text-xs">
            <input type="checkbox" checked={blocking} onChange={(e) => setBlocking(e.target.checked)} /> Blocks approval
          </label>
          <Button type="submit" size="sm" variant="outline" disabled={pending || detail.trim().length < 3}>
            Raise
          </Button>
        </form>
      )}
    </Card>
  )
}

export function Commitments({ c }: { c: CaseDetail }) {
  const { run, pending } = useRunAction(c)
  const invoices = useSnapshotRows(c.snapshot.coverage.includes("invoices") ? c.snapshot.id : null, "invoices")
  const [invoiceId, setInvoiceId] = useState("")
  const [amount, setAmount] = useState("")
  const [date, setDate] = useState("")
  const [quote, setQuote] = useState("")

  return (
    <Card title="Payment commitments" hint="A promise is never a receipt: it changes no balance. Approved ones feed the treasury forecast.">
      {c.commitments.length === 0 && <Empty>No commitments.</Empty>}
      <ul className="divide-y">
        {c.commitments.map((x) => (
          <li key={x.id} className="flex flex-wrap items-center gap-3 py-2.5 text-sm">
            <span className="font-semibold">{x.invoice_number}</span>
            <span>{x.amount}</span>
            <span className={x.expected_date ? "" : "text-amber-800"}>{x.expected_date ?? "no date yet"}</span>
            {x.probability !== "1.0000" && <span className="text-xs">p={x.probability}</span>}
            <Pill label={x.status} tone={x.status === "approved" ? "good" : x.status === "rejected" ? "bad" : "neutral"} />
            {x.quote && <span className="w-full text-xs text-muted-foreground italic">“{x.quote}”</span>}
            {x.status === "proposed" && c.allowed_actions.decide_commitment === null && (
              <span className="flex gap-2">
                <Button size="sm" disabled={pending} onClick={() => void run("decide_commitment", { commitment_id: x.id, decision: "approved" }, "Approved.")}>
                  Approve
                </Button>
                <Button size="sm" variant="outline" disabled={pending} onClick={() => void run("decide_commitment", { commitment_id: x.id, decision: "rejected" }, "Rejected.")}>
                  Reject
                </Button>
              </span>
            )}
          </li>
        ))}
      </ul>
      {c.allowed_actions.propose_commitment === null && (
        <form
          className="mt-3 grid gap-2 border-t pt-3 sm:grid-cols-4"
          onSubmit={(e) => {
            e.preventDefault()
            void run(
              "propose_commitment",
              { invoice_id: invoiceId, amount, expected_date: date || null, quote: quote || null },
              "Commitment proposed.",
            )
          }}
        >
          <select className={selectClass} value={invoiceId} onChange={(e) => setInvoiceId(e.target.value)} aria-label="Invoice">
            <option value="">Invoice…</option>
            {invoices.data?.rows.map((r) => (
              <option key={String(r.id)} value={String(r.id)}>
                {String(r.number)} (open {String(r.balance)})
              </option>
            ))}
          </select>
          <Input placeholder="Amount" inputMode="decimal" value={amount} onChange={(e) => setAmount(e.target.value)} />
          <Input type="date" value={date} onChange={(e) => setDate(e.target.value)} aria-label="Expected date" />
          <Button type="submit" size="sm" variant="outline" disabled={pending || !invoiceId || !amount}>
            Propose
          </Button>
          <Input className="sm:col-span-4" placeholder="The customer's exact words" value={quote} onChange={(e) => setQuote(e.target.value)} />
        </form>
      )}
    </Card>
  )
}

export function OwnedActions({ c }: { c: CaseDetail }) {
  const { run, pending } = useRunAction(c)
  const { data: me } = useCurrentUser()
  const [title, setTitle] = useState("")
  const [owner, setOwner] = useState("")
  const [due, setDue] = useState("")
  const [outcomes, setOutcomes] = useState<Record<string, string>>({})
  const people = [...new Map([[c.owner.id, c.owner.name], ...(me ? [[me.id, me.full_name] as const] : [])]).entries()]
  const allowed = c.allowed_actions.add_action === null

  return (
    <Card title="Owned actions" hint="Follow-ups with a responsible person, a due date and a recorded outcome.">
      {c.owned_actions.length === 0 && <Empty>No actions.</Empty>}
      <ul className="divide-y">
        {c.owned_actions.map((a) => (
          <li key={a.id} className="py-2.5 text-sm">
            <p className="flex flex-wrap items-center gap-2">
              <span className="font-semibold">{a.title}</span>
              <span className="text-xs text-muted-foreground">
                {a.owner.name} · due {a.due_date}
              </span>
              <Pill label={a.status} tone={a.status === "done" ? "good" : a.status === "open" ? "info" : "neutral"} />
            </p>
            {a.outcome && <p className="text-xs italic">{a.outcome}</p>}
            {a.status === "open" && allowed && (
              <div className="mt-2 flex gap-2">
                <Input
                  placeholder="Outcome"
                  value={outcomes[a.id] ?? ""}
                  onChange={(e) => setOutcomes({ ...outcomes, [a.id]: e.target.value })}
                />
                <Button
                  size="sm"
                  variant="outline"
                  disabled={pending || !(outcomes[a.id] ?? "").trim()}
                  onClick={() => void run("update_action", { action_id: a.id, status: "done", outcome: outcomes[a.id] }, "Action closed.")}
                >
                  Done
                </Button>
              </div>
            )}
          </li>
        ))}
      </ul>
      {allowed && (
        <form
          className="mt-3 grid gap-2 border-t pt-3 sm:grid-cols-[1fr_180px_160px_auto]"
          onSubmit={(e) => {
            e.preventDefault()
            void run("add_action", { title, owner_id: owner, due_date: due }, "Action added.")
          }}
        >
          <Input placeholder="Action" value={title} onChange={(e) => setTitle(e.target.value)} />
          <select className={selectClass} value={owner} onChange={(e) => setOwner(e.target.value)} aria-label="Owner">
            <option value="">Owner…</option>
            {people.map(([id, name]) => (
              <option key={id} value={id}>
                {name}
              </option>
            ))}
          </select>
          <Input type="date" value={due} onChange={(e) => setDue(e.target.value)} aria-label="Due date" />
          <Button type="submit" size="sm" variant="outline" disabled={pending || title.trim().length < 3 || !owner || !due}>
            Add
          </Button>
        </form>
      )}
    </Card>
  )
}

export function Decisions({ c }: { c: CaseDetail }) {
  const { run, pending } = useRunAction(c)
  const a = c.allowed_actions
  return (
    <Card title="Decision" hint={`Content fingerprint ${c.fingerprint.slice(0, 12)}…: an approval binds exactly this.`}>
      {c.blockers.length > 0 && (
        <ul className="mb-3 list-disc pl-5 text-sm text-amber-800">
          {c.blockers.map((b) => (
            <li key={b}>{b}</li>
          ))}
        </ul>
      )}
      <div className="flex flex-wrap gap-2">
        {c.status === "draft" && (
          <GuardedButton reason={a.approve} disabled={pending} onClick={() => void run("approve", {}, "Case approved.")}>
            Approve case
          </GuardedButton>
        )}
        {c.status === "approved" && (
          <GuardedButton reason={a.complete} disabled={pending} variant="outline" onClick={() => void run("complete", {}, "Case completed.")}>
            Complete case
          </GuardedButton>
        )}
      </div>
      {c.completion_blockers.length > 0 && c.status === "approved" && (
        <ul className="mt-3 list-disc pl-5 text-xs text-muted-foreground">
          {c.completion_blockers.map((b) => (
            <li key={b}>{b}</li>
          ))}
        </ul>
      )}
      {c.approvals.length > 0 && (
        <ul className="mt-4 space-y-1 border-t pt-3 text-xs">
          {c.approvals.map((ap) => (
            <li key={ap.id} className={ap.valid ? "" : "text-muted-foreground line-through"}>
              Approved by {ap.user.name} · {formatDateTime(ap.created_at)}
              {!ap.valid && " (content changed since)"}
            </li>
          ))}
        </ul>
      )}
    </Card>
  )
}
