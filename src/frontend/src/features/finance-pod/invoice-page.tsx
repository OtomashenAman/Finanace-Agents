import { useState } from "react"
import { Link, useNavigate, useParams } from "react-router"
import {
  Ban,
  Bot,
  Check,
  CircleAlert,
  Copy,
  Download,
  FileSearch,
  Mail,
  PackageCheck,
  RefreshCw,
  Scale,
  Send,
  ShieldAlert,
  Trash2,
} from "lucide-react"

import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Textarea } from "@/components/ui/textarea"
import { AiBadge, AiCard, Card, Field, LoadError, Loading, Pill } from "@/features/service-pod/components/bits"
import { formatDateTime } from "@/features/service-pod/labels"
import { attempt } from "@/features/service-pod/ui"
import { cn } from "@/lib/utils"

import { FpodPage } from "./components/fpod-page"
import { InvoiceForm } from "./components/invoice-form"
import { MatchExplainer } from "./components/match-explainer"
import { useFpodMutation, useInvoice } from "./hooks"
import { invoicesApi, type ExceptionDecision, type Invoice, type InvoiceIn } from "./invoices-api"
import { EXCEPTION_STATUS, formatDate, INVOICE_STATUS, ISSUE_KIND, LINE_STATUS, money } from "./labels"

function toForm(inv: Invoice): InvoiceIn {
  return {
    vendor_code: inv.vendor_code,
    vendor_invoice_number: inv.vendor_invoice_number,
    invoice_date: inv.invoice_date,
    due_date: inv.due_date,
    currency: inv.currency,
    tax_code: inv.tax_code,
    tax_total: inv.tax_total,
    total: inv.total,
    po_reference: inv.po_reference,
    lines: inv.lines.map((l) => ({ description: l.description, quantity: l.quantity, unit_price: l.unit_price, po_line: l.po_line })),
  }
}

/** Where the invoice is in the flow: capture, guard, post, match, resolve, coding. */
function Stepper({ inv }: { inv: Invoice }) {
  const steps = [
    { key: "capture", label: "Captured", done: inv.status !== "captured" || Boolean(inv.validated_at) },
    { key: "guard", label: "Duplicate guard", done: Boolean(inv.posted_at), bad: inv.status === "duplicate" },
    { key: "post", label: "Posted to ERP", done: Boolean(inv.posted_at) },
    { key: "match", label: "Three-way match", done: inv.match_runs > 0, bad: inv.status === "exception" },
    { key: "ready", label: "Ready for coding", done: inv.status === "ready" },
  ]
  return (
    <ol className="flex flex-wrap items-center gap-2 text-xs">
      {steps.map((s, i) => (
        <li key={s.key} className="flex items-center gap-2">
          <span
            className={cn(
              "flex items-center gap-1.5 rounded-full border px-2.5 py-1 font-medium",
              s.bad
                ? "border-amber-300 bg-amber-50 text-amber-900"
                : s.done
                  ? "border-emerald-300 bg-emerald-50 text-emerald-900"
                  : "border-border bg-card text-muted-foreground",
            )}
          >
            {s.done && !s.bad ? <Check className="size-3.5" aria-hidden /> : s.bad ? <CircleAlert className="size-3.5" aria-hidden /> : null}
            {s.label}
          </span>
          {i < steps.length - 1 && <span className="h-px w-4 bg-border" aria-hidden />}
        </li>
      ))}
    </ol>
  )
}

function DuplicateCard({ inv }: { inv: Invoice }) {
  const release = useFpodMutation(invoicesApi.notDuplicate)
  const [note, setNote] = useState("")
  const d = inv.duplicate
  if (!d?.hits?.length) return null
  return (
    <AiCard
      title="Duplicate guard"
      hint="fuzzy match on vendor, invoice number, amount and date. It blocks and explains; a person can release it with a reason."
      badge={<AiBadge label="Posting agent" />}
    >
      <div className="space-y-3 text-sm">
        <p className={cn("flex items-start gap-1.5", d.overridden_by ? "text-muted-foreground" : "text-red-700")}>
          <ShieldAlert className="mt-0.5 size-4 shrink-0" aria-hidden /> {d.explanation}
        </p>
        <ul className="space-y-1">
          {d.hits.map((h) => (
            <li key={h.invoice_id} className="flex flex-wrap items-center gap-2">
              <Pill label={h.strength} tone={h.strength === "exact" ? "bad" : "warn"} />
              <Link to={`/finance-pod/invoices/${h.invoice_id}`} className="font-medium text-primary hover:underline">
                {h.reference}
              </Link>
              <span className="text-muted-foreground">
                {h.vendor_invoice_number} · {money(h.total)} · {formatDate(h.invoice_date)} · {h.status} · {h.reason}
              </span>
            </li>
          ))}
        </ul>
        {d.overridden_by ? (
          <p className="text-xs text-muted-foreground">
            Released by {d.overridden_by}: {d.override_note}
          </p>
        ) : (
          inv.status === "duplicate" && (
            <div className="flex flex-wrap gap-2">
              <Input className="max-w-md" value={note} onChange={(e) => setNote(e.target.value)} placeholder="Why it isn't a duplicate" />
              <Button
                size="sm"
                variant="outline"
                disabled={release.isPending || note.trim().length < 3}
                onClick={() => attempt(() => release.mutateAsync([inv.id, inv.version, note.trim()]), "Released: posted and matched.")}
              >
                Not a duplicate: post it
              </Button>
            </div>
          )
        )}
      </div>
    </AiCard>
  )
}

function MatchCard({ inv }: { inv: Invoice }) {
  const rematch = useFpodMutation(invoicesApi.rematch)
  const m = inv.match
  if (!m) return null
  if (!inv.po_id && m.outcome === "matched")
    return (
      <Card title="No purchase order" hint="Nothing to match line by line.">
        <p className="flex items-center gap-1.5 rounded-lg bg-emerald-50 px-3 py-2 text-sm font-medium text-emerald-900">
          <Check className="size-4" aria-hidden /> {m.note ?? "Approved without a PO: ready to pay."}
        </p>
      </Card>
    )
  const t = m.tolerances
  return (
    <AiCard
      title="Three-way match"
      hint={`line by line against ${inv.po_reference ?? "the PO"} and what was received: an invoice may bill part of a PO (what has arrived), never more than was received or ordered.${t ? ` Tolerances: price ${t.price_pct}% or ${money(t.price_amount)} a unit, quantity ${t.qty_pct}%.` : ""} Run ${inv.match_runs}, ${formatDateTime(m.ran_at)}.`}
      badge={<AiBadge label="Match agent" />}
      actions={
        ["posted", "exception"].includes(inv.status) && (
          <Button size="sm" variant="outline" disabled={rematch.isPending} onClick={() => attempt(() => rematch.mutateAsync([inv.id]), "Matched again.")}>
            <RefreshCw aria-hidden /> Re-match
          </Button>
        )
      }
    >
      <div className="space-y-3 text-sm">
        <p
          className={cn(
            "flex items-center gap-1.5 rounded-lg px-3 py-2 font-medium",
            m.outcome === "matched" ? "bg-emerald-50 text-emerald-900" : "bg-amber-50 text-amber-900",
          )}
        >
          {m.outcome === "matched" ? <Check className="size-4" aria-hidden /> : <Scale className="size-4" aria-hidden />}
          {m.outcome === "matched" ? "Matched: sent to coding" : "Variance: exception opened"}
          {Number(m.credit) > 0 && ` · credit note ${money(m.credit)} applied`}
        </p>
        <MatchExplainer inv={inv} />
        {m.lines.length > 0 && (
          <div className="overflow-x-auto">
            <table className="w-full text-xs">
              <thead className="text-left text-muted-foreground">
                <tr className="border-b border-border">
                  <th className="py-1.5 pr-2 font-medium">Invoice line</th>
                  <th className="py-1.5 pr-2 text-right font-medium">Qty</th>
                  <th className="py-1.5 pr-2 text-right font-medium">Price</th>
                  <th className="py-1.5 pr-2 text-right font-medium">PO price</th>
                  <th className="py-1.5 pr-2 text-right font-medium">Ordered</th>
                  <th className="py-1.5 pr-2 text-right font-medium">Received</th>
                  <th className="py-1.5 pr-2 text-right font-medium">Invoiced before</th>
                  <th className="py-1.5 font-medium">Result</th>
                </tr>
              </thead>
              <tbody>
                {m.lines.map((l) => (
                  <tr key={l.line} className="border-b border-border/50">
                    <td className="py-1.5 pr-2">
                      {l.line}. {l.description}
                      {l.po_line && <span className="text-muted-foreground"> → PO line {l.po_line}</span>}
                    </td>
                    <td className="py-1.5 pr-2 text-right tabular-nums">{Number(l.quantity)}</td>
                    <td className="py-1.5 pr-2 text-right tabular-nums">{money(l.unit_price)}</td>
                    <td className="py-1.5 pr-2 text-right tabular-nums">{l.po_unit_price ? money(l.po_unit_price) : "—"}</td>
                    <td className="py-1.5 pr-2 text-right tabular-nums">{l.po_quantity !== undefined ? Number(l.po_quantity) : "—"}</td>
                    <td className="py-1.5 pr-2 text-right tabular-nums">{l.received !== undefined ? Number(l.received) : "—"}</td>
                    <td className="py-1.5 pr-2 text-right tabular-nums">
                      {l.invoiced_elsewhere !== undefined ? Number(l.invoiced_elsewhere) : "—"}
                    </td>
                    <td className="py-1.5">
                      <Pill label={LINE_STATUS[l.status][0]} tone={LINE_STATUS[l.status][1]} />
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
        {m.issues.length > 0 && (
          <ul className="space-y-1">
            {m.issues.map((i, n) => (
              <li key={n} className="flex items-start gap-1.5 text-amber-900 dark:text-amber-300">
                <CircleAlert className="mt-0.5 size-4 shrink-0" aria-hidden />
                <span>
                  <strong>{ISSUE_KIND[i.kind] ?? i.kind}:</strong> {i.message}
                </span>
              </li>
            ))}
          </ul>
        )}
      </div>
    </AiCard>
  )
}

const DECISIONS: { key: ExceptionDecision; label: string; hint: string }[] = [
  { key: "accept", label: "Accept the variance", hint: "Pay as invoiced; the reason is logged." },
  { key: "credit", label: "Request a credit note", hint: "The vendor gets the drafted query; the invoice waits." },
  { key: "amend_po", label: "Amend the PO", hint: "You change the PO line (agents never do); then it re-matches." },
  { key: "reject", label: "Reject the invoice", hint: "The vendor is told why." },
]

function ExceptionCard({ inv }: { inv: Invoice }) {
  const decide = useFpodMutation(invoicesApi.decide)
  const credit = useFpodMutation(invoicesApi.creditNote)
  const nudge = useFpodMutation(invoicesApi.nudge)
  const e = inv.exception
  const [choice, setChoice] = useState<ExceptionDecision | null>(null)
  const [note, setNote] = useState("")
  const [subject, setSubject] = useState(e?.vendor_query_subject ?? "")
  const [body, setBody] = useState(e?.vendor_query_body ?? "")
  const [amount, setAmount] = useState(inv.match?.price_variance ?? "")
  const [creditRef, setCreditRef] = useState("")
  const [creditAmount, setCreditAmount] = useState(e?.credit_expected ?? "")
  const [link, setLink] = useState<string | null>(null)
  const priced = (inv.match?.lines ?? []).filter((l) => l.po_line)
  const [amend, setAmend] = useState<Record<number, { unit_price: string; quantity: string }>>(() =>
    Object.fromEntries(
      priced.map((l) => [l.po_line!, { unit_price: l.unit_price, quantity: l.po_quantity ?? l.quantity }]),
    ),
  )
  if (!e) return null
  const [label, tone] = EXCEPTION_STATUS[e.status]
  const run = () =>
    attempt(
      () =>
        decide.mutateAsync([
          e.id,
          {
            decision: choice!,
            note,
            credit_expected: choice === "credit" ? amount || null : null,
            query_subject: choice === "credit" || choice === "reject" ? subject : null,
            query_body: choice === "credit" || choice === "reject" ? body : null,
            amendments:
              choice === "amend_po"
                ? Object.entries(amend).map(([k, v]) => ({ po_line: Number(k), unit_price: v.unit_price, quantity: v.quantity }))
                : [],
          },
        ]),
      "Decision recorded.",
    ).then((ok) => ok && setChoice(null))

  return (
    <AiCard
      title={`Exception: ${e.kinds.map((k) => ISSUE_KIND[k] ?? k).join(", ")}`}
      hint={`the exception agent prepared the case and drafted the vendor query. Open ${e.age_days} days.`}
      badge={<AiBadge label="Exception agent" />}
      actions={<Pill label={label} tone={tone} />}
    >
      <div className="space-y-4 text-sm">
        {e.decision && (
          <p className="rounded-lg bg-muted/40 px-3 py-2">
            <strong>{DECISIONS.find((d) => d.key === e.decision)?.label}</strong> by {e.decided_by_name}{" "}
            {e.decided_at && formatDateTime(e.decided_at)}: {e.note}
            {e.credit_expected && ` · credit asked ${money(e.credit_expected)}`}
            {e.credit_received && ` · received ${money(e.credit_received)} (${e.credit_note_ref})`}
          </p>
        )}

        {e.status === "waiting_receipt" && (
          <section className="space-y-2 rounded-lg border border-sky-200 bg-sky-50 p-3 text-sky-900">
            <h3 className="flex items-center gap-1.5 font-semibold">
              <PackageCheck className="size-4" aria-hidden /> Receipt agent
            </h3>
            {inv.receipt_requests.map((r) => (
              <div key={r.id} className="flex flex-wrap items-center justify-between gap-2">
                <span>
                  Asked {r.receiver_name} ({r.receiver_email}) to confirm on their phone · {r.nudges} nudge
                  {r.nudges === 1 ? "" : "s"}
                  {r.last_nudged_at && `, last ${formatDateTime(r.last_nudged_at)}`} · <strong>{r.status}</strong>
                </span>
                {r.status === "open" && (
                  <Button
                    size="sm"
                    variant="outline"
                    disabled={nudge.isPending}
                    onClick={async () => {
                      const res = await attempt(() => nudge.mutateAsync([r.id]), "Receiver nudged again.")
                      if (res?.link) setLink(res.link)
                    }}
                  >
                    <Send aria-hidden /> Nudge again
                  </Button>
                )}
              </div>
            ))}
            {link && (
              <p className="text-xs break-all">
                New link (shown once, for testing): <a className="underline" href={link}>{link}</a>
              </p>
            )}
            <p className="text-xs">Or record the receipt yourself on the request's PO (Receipts).</p>
          </section>
        )}

        {e.status === "waiting_vendor" && (
          <section className="space-y-2 rounded-lg border border-sky-200 bg-sky-50 p-3 text-sky-900">
            <h3 className="font-semibold">Waiting for the vendor's credit note ({money(e.credit_expected)})</h3>
            <div className="flex flex-wrap gap-2">
              <Input className="w-36 bg-white" inputMode="decimal" value={creditAmount} onChange={(x) => setCreditAmount(x.target.value)} placeholder="Amount" />
              <Input className="w-48 bg-white" value={creditRef} onChange={(x) => setCreditRef(x.target.value)} placeholder="Credit note number" />
              <Button
                size="sm"
                disabled={credit.isPending || !creditAmount || !creditRef}
                onClick={() => attempt(() => credit.mutateAsync([e.id, creditAmount, creditRef]), "Credit note recorded; matched again.")}
              >
                Record credit note
              </Button>
            </div>
          </section>
        )}

        {e.status !== "resolved" && (
          <section className="space-y-2">
            <h3 className="font-semibold">Buyer decides</h3>
            <div className="grid gap-2 sm:grid-cols-2">
              {DECISIONS.map((d) => (
                <button
                  key={d.key}
                  type="button"
                  onClick={() => setChoice(d.key)}
                  className={cn(
                    "rounded-lg border p-3 text-left transition-colors",
                    choice === d.key ? "border-primary bg-primary/5" : "border-border hover:bg-muted/40",
                  )}
                >
                  <span className="block font-medium">{d.label}</span>
                  <span className="text-xs text-muted-foreground">{d.hint}</span>
                </button>
              ))}
            </div>
            {choice && (
              <div className="space-y-2 rounded-lg border border-border p-3">
                {choice === "credit" && (
                  <Field label="Credit to ask for">
                    <Input className="w-40" inputMode="decimal" value={amount} onChange={(x) => setAmount(x.target.value)} />
                  </Field>
                )}
                {choice === "amend_po" && (
                  <div className="space-y-1">
                    <p className="text-xs text-muted-foreground">New values for {inv.po_reference}'s lines (you change the PO, recorded old and new):</p>
                    {Object.entries(amend).map(([k, v]) => (
                      <div key={k} className="flex items-center gap-2">
                        <span className="w-20">Line {k}</span>
                        <Input className="w-28" inputMode="decimal" value={v.quantity} onChange={(x) => setAmend({ ...amend, [k]: { ...v, quantity: x.target.value } })} aria-label={`PO line ${k} quantity`} />
                        <span>×</span>
                        <Input className="w-32" inputMode="decimal" value={v.unit_price} onChange={(x) => setAmend({ ...amend, [k]: { ...v, unit_price: x.target.value } })} aria-label={`PO line ${k} price`} />
                      </div>
                    ))}
                  </div>
                )}
                {(choice === "credit" || choice === "reject") && (
                  <div className="space-y-1">
                    <p className="flex items-center gap-1.5 text-xs text-muted-foreground">
                      <Mail className="size-3.5" aria-hidden /> Vendor query drafted by the exception agent (edit before sending):
                    </p>
                    <Input value={subject} onChange={(x) => setSubject(x.target.value)} />
                    <Textarea rows={7} value={body} onChange={(x) => setBody(x.target.value)} />
                  </div>
                )}
                <Field label="Your reason (logged)">
                  <Input value={note} onChange={(x) => setNote(x.target.value)} />
                </Field>
                <Button size="sm" disabled={decide.isPending || note.trim().length < 3} onClick={() => void run()}>
                  Confirm: {DECISIONS.find((d) => d.key === choice)?.label}
                </Button>
              </div>
            )}
          </section>
        )}
      </div>
    </AiCard>
  )
}

function Details({ inv }: { inv: Invoice }) {
  return (
    <Card
      title="Invoice"
      actions={
        inv.filename && (
          <Button size="sm" variant="outline" onClick={() => invoicesApi.downloadFile(inv)}>
            <Download aria-hidden /> {inv.filename}
          </Button>
        )
      }
    >
      <dl className="grid gap-x-6 gap-y-2 text-sm sm:grid-cols-2">
        {(
          [
            ["Vendor", `${inv.vendor_name ?? "—"}${inv.vendor_code ? ` (${inv.vendor_code})` : ""}`],
            ["Vendor's number", inv.vendor_invoice_number ?? "—"],
            ["Invoice date", formatDate(inv.invoice_date)],
            ["Due", formatDate(inv.due_date)],
            ["Our PO", inv.po_reference ?? "—"],
            ["Total", money(inv.total, inv.currency)],
            ["Posted", inv.posted_at ? `${inv.erp_system} ERP ${inv.erp_ref} · ${formatDateTime(inv.posted_at)}` : "—"],
            ["Released to coding", inv.released_at ? formatDateTime(inv.released_at) : "—"],
          ] as [string, string][]
        ).map(([k, v]) => (
          <div key={k} className="flex justify-between gap-3 border-b border-border/50 pb-1">
            <dt className="text-muted-foreground">{k}</dt>
            <dd className="text-right font-medium">{v}</dd>
          </div>
        ))}
      </dl>
      <table className="mt-3 w-full text-sm">
        <tbody>
          {inv.lines.map((l) => (
            <tr key={l.position} className="border-b border-border/50">
              <td className="py-1.5 pr-2">
                {l.position}. {l.description}
              </td>
              <td className="py-1.5 pr-2 text-right tabular-nums">
                {Number(l.quantity)} × {money(l.unit_price)}
              </td>
              <td className="py-1.5 text-right tabular-nums">{money(l.amount)}</td>
            </tr>
          ))}
        </tbody>
      </table>
      {inv.rejected_reason && <p className="mt-2 text-sm text-red-700">Rejected: {inv.rejected_reason}</p>}
    </Card>
  )
}

export function InvoicePage() {
  const { invoiceId } = useParams()
  const navigate = useNavigate()
  const q = useInvoice(invoiceId)
  const update = useFpodMutation(invoicesApi.update)
  const post = useFpodMutation(invoicesApi.post)
  const reject = useFpodMutation(invoicesApi.reject)
  const remove = useFpodMutation(invoicesApi.remove)
  const inv = q.data
  return (
    <FpodPage title={inv ? `${inv.reference}: ${inv.vendor_name ?? "invoice"}` : "Invoice"}>
      {q.isPending ? (
        <Loading what="the invoice" />
      ) : q.isError || !inv ? (
        <LoadError what="the invoice" />
      ) : (
        <div className="space-y-5">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <div className="flex flex-wrap items-center gap-2 text-sm">
              <Link to="/finance-pod/invoices" className="text-primary hover:underline">
                ← All invoices
              </Link>
              <Pill label={INVOICE_STATUS[inv.status][0]} tone={INVOICE_STATUS[inv.status][1]} />
              <span className="font-semibold tabular-nums">{money(inv.total, inv.currency)}</span>
              {inv.payment_ref && (
                <span className="text-xs text-muted-foreground">
                  paid {formatDate(inv.paid_at)} · ref {inv.payment_ref}
                </span>
              )}
            </div>
            <div className="flex gap-1">
              {!["ready", "paid", "rejected"].includes(inv.status) && (
                <Button
                  size="sm"
                  variant="ghost"
                  disabled={reject.isPending}
                  onClick={() => {
                    const reason = window.prompt("Why reject this invoice?")
                    if (reason?.trim()) void attempt(() => reject.mutateAsync([inv.id, inv.version, reason.trim()]), "Invoice rejected.")
                  }}
                >
                  <Ban aria-hidden /> Reject
                </Button>
              )}
              <Button
                size="sm"
                variant="ghost"
                className="text-red-700 hover:text-red-800"
                disabled={remove.isPending}
                onClick={async () => {
                  if (!window.confirm(`Delete ${inv.reference}? Its exception goes too; the audit trail keeps a record.`)) return
                  const ok = await attempt(() => remove.mutateAsync([[inv.id]]), `${inv.reference} deleted.`)
                  if (ok) navigate("/finance-pod/invoices")
                }}
              >
                <Trash2 aria-hidden /> Delete
              </Button>
            </div>
          </div>
          <Stepper inv={inv} />

          {inv.can_edit ? (
            <AiCard
              title="Check the invoice data"
              hint={
                inv.extraction?.error
                  ? `The capture agent couldn't read it all (${inv.extraction.error}): fill in what's missing.`
                  : inv.extraction
                    ? `Read by the capture agent${inv.extraction.verified ? ", every figure checked against the document's text" : " from an image: check the figures"}. Correct anything, then post.`
                    : "Keyed by hand. Check it, then post."
              }
              badge={<AiBadge label={inv.extraction ? "Capture agent" : "Manual"} />}
              actions={
                inv.filename && (
                  <Button size="sm" variant="outline" onClick={() => invoicesApi.downloadFile(inv)}>
                    <FileSearch aria-hidden /> Open the document
                  </Button>
                )
              }
            >
              <InvoiceForm
                key={inv.version}
                initial={toForm(inv)}
                saving={update.isPending}
                submitLabel="Save"
                onSubmit={(body) => void attempt(() => update.mutateAsync([inv.id, inv.version, body]), "Saved.")}
                extra={
                  <Button
                    type="button"
                    variant="default"
                    className="bg-emerald-700 hover:bg-emerald-800"
                    disabled={post.isPending}
                    onClick={async () => {
                      const res = await attempt(() => post.mutateAsync([inv.id, inv.version]), (r) =>
                        r.status === "duplicate"
                          ? "Blocked by the duplicate guard."
                          : r.status === "ready"
                            ? "Posted and matched: ready for coding."
                            : "Posted; the match found an exception.",
                      )
                      if (res) navigate(`/finance-pod/invoices/${res.id}`)
                    }}
                  >
                    <Bot aria-hidden /> Confirm data and post
                  </Button>
                }
              />
            </AiCard>
          ) : (
            <Details inv={inv} />
          )}
          <DuplicateCard inv={inv} />
          <ExceptionCard key={`${inv.exception?.id}-${inv.version}`} inv={inv} />
          <MatchCard inv={inv} />
          {inv.duplicate?.hits?.length && inv.can_edit ? (
            <p className="flex items-center gap-1 text-xs text-muted-foreground">
              <Copy className="size-3.5" aria-hidden /> Editing a blocked invoice runs the duplicate guard again when you post.
            </p>
          ) : null}
        </div>
      )}
    </FpodPage>
  )
}
