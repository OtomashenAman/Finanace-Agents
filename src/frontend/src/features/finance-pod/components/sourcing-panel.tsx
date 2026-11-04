import { useRef, useState } from "react"
import { Link } from "react-router"
import { Download, Mail, Paperclip, Plus, RefreshCw, Send, Sparkles } from "lucide-react"

import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Textarea } from "@/components/ui/textarea"
import { AiBadge, AiCard, Card, Empty, Field, LoadError, Loading, Pill } from "@/features/service-pod/components/bits"
import { formatDateTime, type Tone } from "@/features/service-pod/labels"
import { attempt, selectClass } from "@/features/service-pod/ui"
import { cn } from "@/lib/utils"

import type { PurchaseRequest } from "../api"
import { useFpodMutation, useReference, useSourcing } from "../hooks"
import { formatDate, money } from "../labels"
import { procurementApi, type ComparisonRow, type Quote, type QuoteIn, type Sourcing } from "../procurement-api"

const QUOTE_STATUS: Record<Quote["status"], [string, Tone]> = {
  requested: ["Requested", "info"],
  received: ["Received", "good"],
  declined: ["Declined", "neutral"],
}

const in7days = () => new Date(Date.now() + 7 * 86_400_000).toISOString().slice(0, 10)

/** Why the agent found nobody, in the requester's terms. */
function NoCandidates({ r }: { r: PurchaseRequest }) {
  const uncategorised = r.lines.filter((l) => !l.category).length
  const categories = [...new Set(r.lines.map((l) => l.category).filter(Boolean))]
  return (
    <p className="rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 text-xs text-amber-900">
      The sourcing agent found no approved vendor for this request: none has contract prices for its items
      {categories.length > 0 && <>, and none is approved for {categories.join(", ")}</>}
      {uncategorised > 0 && (
        <>
          {" "}
          ({uncategorised} line{uncategorised === 1 ? " has" : "s have"} no category, so they can't be matched to a
          vendor's categories)
        </>
      )}
      . Pick a vendor from the vendor master below, invite a new one by name and email, or add a quote you already
      have. To have the agent find vendors next time, give them categories (and contract prices) in the reference
      workbook.
    </p>
  )
}

function OtherVendors({ s, picked, onPick }: { s: Sourcing; picked: string[]; onPick: (code: string) => void }) {
  const reference = useReference()
  const suggested = new Set(s.candidates.map((c) => c.vendor_code))
  const others = (reference.data?.vendors ?? []).filter(
    (v) => v.status === "approved" && !suggested.has(v.code) && !picked.includes(v.code),
  )
  if (others.length === 0) return null
  return (
    <Field label="Any approved vendor from the vendor master">
      <select
        className={selectClass}
        value=""
        onChange={(e) => {
          if (e.target.value) onPick(e.target.value)
        }}
      >
        <option value="">Add a vendor…</option>
        {others.map((v) => (
          <option key={v.code} value={v.code} disabled={!v.email}>
            {v.name} ({v.code}){v.categories.length ? ` · ${v.categories.join(", ")}` : ""}
            {!v.email ? " · no email on file" : ""}
          </option>
        ))}
      </select>
    </Field>
  )
}

/** A quote that came in another way (phone, the vendor's own email, a portal). */
function AddQuote({ r }: { r: PurchaseRequest }) {
  const add = useFpodMutation(procurementApi.addQuote)
  const reference = useReference()
  const [open, setOpen] = useState(false)
  const [code, setCode] = useState("")
  const [name, setName] = useState("")
  const [email, setEmail] = useState("")
  const [total, setTotal] = useState("")
  const [lead, setLead] = useState("")
  const [terms, setTerms] = useState("")
  const [valid, setValid] = useState("")
  if (!open) {
    return (
      <Button size="sm" variant="outline" onClick={() => setOpen(true)}>
        <Plus aria-hidden /> Add a quote you already have
      </Button>
    )
  }
  const vendors = (reference.data?.vendors ?? []).filter((v) => v.status === "approved")
  const ready = Boolean(total) && (Boolean(code) || (name.trim() && email.trim()))
  return (
    <div className="space-y-2 rounded-lg border border-border bg-muted/30 p-3">
      <p className="font-medium">Add a quote you already have</p>
      <div className="grid gap-2 sm:grid-cols-3">
        <Field label="Vendor">
          <select className={selectClass} value={code} onChange={(e) => setCode(e.target.value)}>
            <option value="">New vendor (name and email)</option>
            {vendors.map((v) => (
              <option key={v.code} value={v.code}>
                {v.name} ({v.code})
              </option>
            ))}
          </select>
        </Field>
        {!code && (
          <>
            <Field label="New vendor name">
              <Input value={name} onChange={(e) => setName(e.target.value)} />
            </Field>
            <Field label="Their email">
              <Input type="email" value={email} onChange={(e) => setEmail(e.target.value)} />
            </Field>
          </>
        )}
        <Field label={`Total (${r.currency})`}>
          <Input inputMode="decimal" value={total} onChange={(e) => setTotal(e.target.value)} />
        </Field>
        <Field label="Lead time (days)">
          <Input type="number" min={0} value={lead} onChange={(e) => setLead(e.target.value)} />
        </Field>
        <Field label="Payment terms">
          <Input value={terms} onChange={(e) => setTerms(e.target.value)} placeholder="e.g. Net 30" />
        </Field>
        <Field label="Valid until">
          <Input type="date" value={valid} onChange={(e) => setValid(e.target.value)} />
        </Field>
      </div>
      <div className="flex gap-2">
        <Button
          size="sm"
          disabled={add.isPending || !ready}
          onClick={async () => {
            const ok = await attempt(
              () =>
                add.mutateAsync([
                  r.id,
                  {
                    ...(code ? { vendor_code: code } : { vendor_name: name.trim(), vendor_email: email.trim() }),
                    status: "received",
                    total,
                    currency: r.currency,
                    lead_time_days: lead ? Number(lead) : null,
                    payment_terms: terms || null,
                    valid_until: valid || null,
                    notes: null,
                  },
                ]),
              "Quote added. Attach the document if you have it: the agent will check it.",
            )
            if (ok) setOpen(false)
          }}
        >
          Add quote
        </Button>
        <Button size="sm" variant="ghost" onClick={() => setOpen(false)}>
          Cancel
        </Button>
      </div>
    </div>
  )
}

function RequestQuotes({ r, s }: { r: PurchaseRequest; s: Sourcing }) {
  const send = useFpodMutation(procurementApi.requestQuotes)
  const reference = useReference()
  const [picked, setPicked] = useState<string[]>([])
  const [newName, setNewName] = useState("")
  const [newEmail, setNewEmail] = useState("")
  const [replyBy, setReplyBy] = useState(in7days())
  const [message, setMessage] = useState("")
  const vendors = [
    ...picked.map((code) => ({ vendor_code: code })),
    ...(newName.trim() && newEmail.trim() ? [{ vendor_name: newName.trim(), vendor_email: newEmail.trim() }] : []),
  ]
  const suggested = new Set(s.candidates.map((c) => c.vendor_code))
  const extra = picked
    .filter((code) => !suggested.has(code))
    .map((code) => reference.data?.vendors.find((v) => v.code === code))
    .filter((v) => v !== undefined)
  return (
    <section aria-label="Request quotes" className="space-y-2">
      <h3 className="font-semibold">Request quotes</h3>
      {s.candidates.length === 0 && <NoCandidates r={r} />}
      {extra.length > 0 && (
        <ul className="space-y-1">
          {extra.map((v) => (
            <li key={v.code} className="flex items-center gap-2">
              <input
                type="checkbox"
                checked
                onChange={() => setPicked((p) => p.filter((x) => x !== v.code))}
                aria-label={`Remove ${v.name}`}
              />
              <span>
                <strong>{v.name}</strong> ({v.code}) · from the vendor master
              </span>
            </li>
          ))}
        </ul>
      )}
      <OtherVendors s={s} picked={picked} onPick={(code) => setPicked((p) => [...p, code])} />
      {s.candidates.length > 0 && (
        <ul className="space-y-1">
          {s.candidates.map((c) => (
            <li key={c.vendor_code}>
              <label className="flex items-start gap-2">
                <input
                  type="checkbox"
                  className="mt-1"
                  checked={picked.includes(c.vendor_code)}
                  disabled={!c.vendor_email}
                  onChange={(e) =>
                    setPicked((p) => (e.target.checked ? [...p, c.vendor_code] : p.filter((x) => x !== c.vendor_code)))
                  }
                />
                <span>
                  <strong>{c.vendor_name}</strong> ({c.vendor_code}) · {c.reasons.join("; ")}
                  {c.contract_total && ` · contract total ${money(c.contract_total, r.currency)}`}
                  {!c.vendor_email && <span className="text-xs text-muted-foreground"> · no email on file</span>}
                </span>
              </label>
            </li>
          ))}
        </ul>
      )}
      <div className="grid gap-2 sm:grid-cols-2">
        <Input placeholder="Another vendor: name" value={newName} onChange={(e) => setNewName(e.target.value)} />
        <Input placeholder="Their email" type="email" value={newEmail} onChange={(e) => setNewEmail(e.target.value)} />
      </div>
      <div className="grid gap-2 sm:grid-cols-[180px_1fr]">
        <Field label="Reply by">
          <Input type="date" value={replyBy} onChange={(e) => setReplyBy(e.target.value)} />
        </Field>
        <Field label="Extra note to vendors (optional)">
          <Input value={message} maxLength={2000} onChange={(e) => setMessage(e.target.value)} />
        </Field>
      </div>
      <Button
        size="sm"
        disabled={send.isPending || vendors.length === 0}
        onClick={async () => {
          const ok = await attempt(
            () => send.mutateAsync([r.id, vendors, replyBy, message]),
            `Quote request sent to ${vendors.length} vendor${vendors.length === 1 ? "" : "s"}.`,
          )
          if (ok) {
            setPicked([])
            setNewName("")
            setNewEmail("")
          }
        }}
      >
        <Send aria-hidden /> Send quote requests
      </Button>
      <p className="text-xs text-muted-foreground">
        The agent's email lists the items and the needed-by date, never our estimate or budget.
      </p>
      <AddQuote r={r} />
    </section>
  )
}

function QuoteRow({ r, q, editable }: { r: PurchaseRequest; q: Quote; editable: boolean }) {
  const update = useFpodMutation(procurementApi.updateQuote)
  const attach = useFpodMutation(procurementApi.attachQuote)
  const input = useRef<HTMLInputElement>(null)
  const [editing, setEditing] = useState(false)
  const [form, setForm] = useState<QuoteIn>({
    status: q.status === "requested" ? "received" : q.status,
    total: q.total,
    currency: q.currency,
    lead_time_days: q.lead_time_days,
    payment_terms: q.payment_terms,
    valid_until: q.valid_until,
    notes: q.notes,
  })
  return (
    <li className="space-y-2 border-b border-border/50 py-2">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <span>
          <strong>{q.vendor_name}</strong> {q.vendor_code ? `(${q.vendor_code})` : <Pill label="new vendor" tone="warn" />}{" "}
          <Pill label={QUOTE_STATUS[q.status][0]} tone={QUOTE_STATUS[q.status][1]} />
          <span className="ml-2 tabular-nums">{q.total ? money(q.total, q.currency ?? r.currency) : ""}</span>
          <span className="block text-xs text-muted-foreground">
            {q.lead_time_days !== null && `${q.lead_time_days} days lead time · `}
            {q.payment_terms && `${q.payment_terms} · `}
            {q.valid_until && `valid until ${formatDate(q.valid_until)} · `}
            {q.requested_at && `requested ${formatDateTime(q.requested_at)}`}
          </span>
          {q.ai_read && (
            <span className="mt-0.5 flex items-center gap-1 text-xs text-violet-700 dark:text-violet-300">
              <Sparkles className="size-3" aria-hidden /> Read by the sourcing agent
              {q.ai_read.verified ? " (checked against the document's text)" : " (from an image: confirm the figures)"}
            </span>
          )}
        </span>
        <span className="flex gap-1">
          {q.filename && (
            <Button size="sm" variant="ghost" onClick={() => procurementApi.downloadQuote(r.id, q)}>
              <Download aria-hidden /> {q.filename}
            </Button>
          )}
          {editable && (
            <>
              <Input
                ref={input}
                type="file"
                className="hidden"
                accept=".pdf,.png,.jpg,.jpeg,.txt,.xlsx,.docx"
                onChange={async (e) => {
                  const file = e.target.files?.[0]
                  e.target.value = ""
                  if (file) await attempt(() => attach.mutateAsync([r.id, q.id, file]), "Quote attached; the agent read it.")
                }}
              />
              <Button size="sm" variant="outline" disabled={attach.isPending} onClick={() => input.current?.click()}>
                <Paperclip aria-hidden /> {attach.isPending ? "Reading…" : "Attach quote"}
              </Button>
              <Button size="sm" variant="outline" onClick={() => setEditing((v) => !v)}>
                {editing ? "Close" : "Record"}
              </Button>
            </>
          )}
        </span>
      </div>
      {editing && (
        <div className="grid gap-2 rounded-lg bg-muted/30 p-2 sm:grid-cols-3 lg:grid-cols-6">
          <Field label="Status">
            <select
              className={selectClass}
              value={form.status}
              onChange={(e) => setForm({ ...form, status: e.target.value as QuoteIn["status"] })}
            >
              <option value="received">Received</option>
              <option value="declined">Declined</option>
              <option value="requested">Requested</option>
            </select>
          </Field>
          <Field label="Total">
            <Input inputMode="decimal" value={form.total ?? ""} onChange={(e) => setForm({ ...form, total: e.target.value || null })} />
          </Field>
          <Field label="Lead time (days)">
            <Input
              type="number"
              min={0}
              value={form.lead_time_days ?? ""}
              onChange={(e) => setForm({ ...form, lead_time_days: e.target.value ? Number(e.target.value) : null })}
            />
          </Field>
          <Field label="Payment terms">
            <Input value={form.payment_terms ?? ""} onChange={(e) => setForm({ ...form, payment_terms: e.target.value || null })} />
          </Field>
          <Field label="Valid until">
            <Input type="date" value={form.valid_until ?? ""} onChange={(e) => setForm({ ...form, valid_until: e.target.value || null })} />
          </Field>
          <div className="flex items-end">
            <Button
              size="sm"
              disabled={update.isPending}
              onClick={async () => {
                const ok = await attempt(() => update.mutateAsync([r.id, q.id, form]), "Quote recorded.")
                if (ok) setEditing(false)
              }}
            >
              Save
            </Button>
          </div>
        </div>
      )}
    </li>
  )
}

function Comparison({ r, s }: { r: PurchaseRequest; s: Sourcing }) {
  const choose = useFpodMutation(procurementApi.choose)
  const [picked, setPicked] = useState<ComparisonRow | null>(null)
  const [terms, setTerms] = useState("")
  const [delivery, setDelivery] = useState(r.needed_by ?? "")
  const [justification, setJustification] = useState("")
  const short = s.quotes_received < s.quotes_needed
  if (s.comparison.length === 0) {
    return <Empty>No received quotes or full contract coverage yet to compare.</Empty>
  }
  return (
    <div className="space-y-3">
      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead className="text-left text-xs text-muted-foreground">
            <tr className="border-b border-border">
              <th className="py-1.5 pr-2 font-medium">Vendor</th>
              <th className="py-1.5 pr-2 text-right font-medium">Total</th>
              <th className="py-1.5 pr-2 text-right font-medium">vs estimate</th>
              <th className="py-1.5 pr-2 font-medium">Lead time</th>
              <th className="py-1.5 pr-2 font-medium">Terms</th>
              <th className="py-1.5 pr-2 font-medium">Valid until</th>
              <th className="py-1.5 font-medium" />
            </tr>
          </thead>
          <tbody>
            {s.comparison.map((row) => (
              <tr
                key={row.quote_id ?? `contract-${row.vendor_code}`}
                className={cn("border-b border-border/50 align-top", row.expired && "opacity-60")}
              >
                <td className="py-1.5 pr-2">
                  <strong>{row.vendor_name}</strong> {row.option === "contract" && <span className="text-xs">(contract)</span>}
                  <span className="mt-0.5 flex flex-wrap gap-1">
                    {row.flags.map((f) => (
                      <Pill key={f} label={f} tone={f.startsWith("lowest") ? "good" : f.startsWith("new") || f === "expired" ? "warn" : "info"} />
                    ))}
                  </span>
                </td>
                <td className="py-1.5 pr-2 text-right tabular-nums">{money(row.total, r.currency)}</td>
                <td className={cn("py-1.5 pr-2 text-right tabular-nums", Number(row.vs_estimate) > 0 ? "text-red-700" : "text-emerald-700")}>
                  {Number(row.vs_estimate) > 0 ? "+" : ""}
                  {money(row.vs_estimate)}
                </td>
                <td className="py-1.5 pr-2">
                  {row.lead_time_days !== null ? `${row.lead_time_days} d` : "—"}
                  {row.meets_needed_by === false && <span className="block text-xs text-red-700">after needed-by</span>}
                </td>
                <td className="py-1.5 pr-2">{row.payment_terms ?? "—"}</td>
                <td className="py-1.5 pr-2">{formatDate(row.valid_until)}</td>
                <td className="py-1.5">
                  {s.can_change && !row.expired && (
                    <Button
                      size="sm"
                      variant={picked === row ? "default" : "outline"}
                      onClick={() => {
                        setPicked(row)
                        setTerms(row.payment_terms ?? "")
                      }}
                    >
                      Choose
                    </Button>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {picked && (
        <div className="space-y-2 rounded-lg border border-primary/30 bg-primary/5 p-3">
          <p className="font-medium">
            Buyer's choice: {picked.vendor_name} at {money(picked.total, r.currency)}
            {picked.new_vendor && " (new vendor: onboarding starts and the PO waits for it)"}
          </p>
          <div className="grid gap-2 sm:grid-cols-2">
            <Field label="Payment terms">
              <Input value={terms} maxLength={200} onChange={(e) => setTerms(e.target.value)} placeholder="e.g. Net 30" />
            </Field>
            <Field label="Delivery date">
              <Input type="date" value={delivery} onChange={(e) => setDelivery(e.target.value)} />
            </Field>
          </div>
          <Field
            label={short && picked.option === "quote" ? `Justification (required: ${s.quotes_received} of ${s.quotes_needed} quotes)` : "Justification (optional)"}
          >
            <Textarea rows={2} value={justification} maxLength={2000} onChange={(e) => setJustification(e.target.value)} />
          </Field>
          <Button
            size="sm"
            disabled={choose.isPending || !terms.trim()}
            onClick={async () => {
              const ok = await attempt(
                () =>
                  choose.mutateAsync([
                    r.id,
                    {
                      quote_id: picked.option === "quote" ? picked.quote_id : null,
                      contract_vendor_code: picked.option === "contract" ? picked.vendor_code : null,
                      payment_terms: terms,
                      delivery_date: delivery || null,
                      justification,
                    },
                  ]),
                picked.new_vendor ? "Vendor chosen; the onboarding portal link was sent." : "Vendor and terms confirmed.",
              )
              if (ok) setPicked(null)
            }}
          >
            Confirm vendor and terms
          </Button>
        </div>
      )}
    </div>
  )
}

/** the sourcing agent's vendors and quotes, the comparison, the buyer's choice. */
export function SourcingPanel({ r }: { r: PurchaseRequest }) {
  const sourcing = useSourcing(r.id, r.status === "approved" || r.status === "ordered")
  const refresh = useFpodMutation(procurementApi.refreshSourcing)
  if (r.status !== "approved" && r.status !== "ordered") return null
  if (sourcing.isPending) return <Loading what="sourcing" />
  if (sourcing.isError) return <LoadError what="sourcing" />
  const s = sourcing.data
  return (
    <AiCard
      title="Sourcing: select vendor"
      hint={
        s.quotes_needed
          ? `at or above the purchasing threshold, ${s.quotes_needed} quotes are required (${s.quotes_received} received).`
          : "below the purchasing threshold, no quotes are required. Contract prices can be used directly."
      }
      badge={<AiBadge label="Sourcing agent" />}
      actions={
        s.can_change && (
          <Button size="sm" variant="outline" disabled={refresh.isPending} onClick={() => attempt(() => refresh.mutateAsync([r.id]), "Sourcing agent re-ran.")}>
            <RefreshCw aria-hidden /> Re-run agent
          </Button>
        )
      }
    >
      <div className="space-y-5 text-sm">
        {s.status !== "open" && (
          <p
            className={cn(
              "rounded-lg border px-3 py-2",
              s.status === "chosen" ? "border-emerald-200 bg-emerald-50 text-emerald-900" : "border-amber-200 bg-amber-50 text-amber-900",
            )}
          >
            {s.status === "chosen" ? "Chosen" : "Waiting for onboarding"}: <strong>{s.chosen_vendor_name}</strong> at{" "}
            {money(s.chosen_total, r.currency)}, {s.payment_terms}
            {s.delivery_date && `, delivery ${formatDate(s.delivery_date)}`} · by {s.decided_by_name}
            {s.justification && <span className="block text-xs">Justification: {s.justification}</span>}
            {s.onboarding_id && s.status === "awaiting_vendor" && (
              <Link to={`/finance-pod/vendors/${s.onboarding_id}`} className="block text-xs font-medium underline">
                Open the vendor's onboarding →
              </Link>
            )}
          </p>
        )}
        <section aria-label="Comparison">
          <h3 className="mb-1 font-semibold">Side by side</h3>
          <Comparison r={r} s={s} />
        </section>
        <section aria-label="Quotes">
          <h3 className="mb-1 font-semibold">Quotes</h3>
          {s.quotes.length === 0 ? (
            <p className="text-muted-foreground">No quotes yet.</p>
          ) : (
            <ul>
              {s.quotes.map((q) => (
                <QuoteRow key={q.id} r={r} q={q} editable={s.can_change} />
              ))}
            </ul>
          )}
        </section>
        {s.can_change && <RequestQuotes r={r} s={s} />}
        {s.emails.length > 0 && (
          <Card title="Quote request emails" className="shadow-none">
            <ul className="space-y-1 text-xs">
              {s.emails.map((e) => (
                <li key={e.id} className="flex items-start gap-1.5">
                  <Mail className="mt-0.5 size-3.5 shrink-0" aria-hidden />
                  <span>
                    {e.to_email} · {e.status}
                    {e.simulated && " (outbox: simulated)"} · {formatDateTime(e.created_at)}
                    {e.error && <span className="text-red-700"> · {e.error}</span>}
                  </span>
                </li>
              ))}
            </ul>
          </Card>
        )}
      </div>
    </AiCard>
  )
}
