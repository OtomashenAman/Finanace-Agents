import { Link } from "react-router"

import type { CaseDetail } from "../../api"
import { Card, Pill } from "../../components/bits"
import { ARTIFACT_KIND, CASE_STATUS, MESSAGE_STATUS } from "../../labels"
import { money, type InvoiceState } from "../shared"
import { CheckRow } from "../shared-ui"
import { daysUntil, promiseLabel } from "./meta"

interface ArState {
  customer?: { name: string; email: string | null }
  invoices?: (InvoiceState & { original_amount?: string; terms?: string | null })[]
  contract?: { id: string; terms: string | null } | null
  total_open?: string
  currency?: string
}

/** Deck AR screen 2: the invoices, what's promised against them and what QuickBooks shows
 *  as paid. Promises stay in the case: never a receipt. */
export function ArInvoices({ c }: { c: CaseDetail }) {
  const s = c.state as ArState
  const cur = s.currency
  const live = c.commitments.filter((x) => x.status !== "rejected")
  const sum = (xs: { amount: string }[]) => xs.reduce((t, x) => t + Number(x.amount), 0)
  const withTerms = (s.invoices ?? []).some((i) => i.terms)

  return (
    <Card
      title={s.customer?.name ?? "Customer"}
      hint={s.customer?.email ? `Verified contact: ${s.customer.email}` : "No verified contact in the source: mail can't be sent"}
    >
      <div className="overflow-x-auto">
        <table className="w-full min-w-[520px] text-sm">
          <thead>
            <tr className="border-b text-left text-xs text-muted-foreground uppercase">
              <th className="py-1.5 pr-3 font-semibold">Invoice</th>
              <th className="py-1.5 pr-3 font-semibold">Due</th>
              {withTerms && <th className="py-1.5 pr-3 font-semibold">Terms</th>}
              <th className="py-1.5 pr-3 text-right font-semibold">Open</th>
              <th className="py-1.5 pr-3 text-right font-semibold">Promised</th>
              <th className="py-1.5 text-right font-semibold">Paid in QB</th>
            </tr>
          </thead>
          <tbody className="divide-y">
            {(s.invoices ?? []).map((inv) => {
              const mine = live.filter((x) => x.invoice_number === inv.number)
              const approved = mine.filter((x) => x.status === "approved")
              const proposed = mine.filter((x) => x.status === "proposed")
              const paid = Number(inv.original_amount ?? inv.balance) - Number(inv.balance)
              return (
                <tr key={inv.id}>
                  <td className="py-1.5 pr-3 font-medium">{inv.number}</td>
                  <td className="py-1.5 pr-3">
                    {inv.due_date}
                    {inv.days_overdue !== undefined && <span className="ml-1 text-xs text-muted-foreground">({inv.days_overdue} d)</span>}
                  </td>
                  {withTerms && <td className="py-1.5 pr-3 text-xs">{inv.terms ?? "-"}</td>}
                  <td className="py-1.5 pr-3 text-right tabular-nums">{money(inv.balance, cur)}</td>
                  <td className="py-1.5 pr-3 text-right tabular-nums">
                    {mine.length === 0 ? "-" : money(sum(approved), cur)}
                    {proposed.length > 0 && <span className="block text-xs text-amber-800">+ {money(sum(proposed), cur)} proposed</span>}
                  </td>
                  <td className="py-1.5 text-right tabular-nums">{money(paid, cur)}</td>
                </tr>
              )
            })}
          </tbody>
          <tfoot>
            <tr className="border-t font-semibold">
              <td className="py-1.5 pr-3" colSpan={withTerms ? 3 : 2}>
                Total
              </td>
              <td className="py-1.5 pr-3 text-right tabular-nums">{money(s.total_open, cur)}</td>
              <td className="py-1.5 pr-3 text-right tabular-nums">{money(sum(live.filter((x) => x.status === "approved")), cur)}</td>
              <td className="py-1.5 text-right text-xs font-normal text-muted-foreground">from the source</td>
            </tr>
          </tfoot>
        </table>
      </div>
      <ArAttachments c={c} />
    </Card>
  )
}

/** What may go with the email: the agreement the invoices fall under (MSA) and documents
 *  the customer asked for. Only approved files can be attached, ticked in the draft. */
function ArAttachments({ c }: { c: CaseDetail }) {
  const s = c.state as ArState
  const approved = c.artifacts.filter((a) => a.status === "approved")
  const msa = approved.find((a) => a.kind === "msa")
  const pending = c.artifacts.some((a) => a.kind === "msa" && a.status === "pending")
  if (!s.contract && approved.length === 0) return null
  return (
    <ul className="mt-3 divide-y border-t pt-2 text-xs">
      {s.contract && (
        <CheckRow state={msa ? "done" : "waiting"} label="Agreement">
          {s.contract.id}
          {s.contract.terms && ` (${s.contract.terms})`}:{" "}
          {msa
            ? `${msa.filename} approved: tick it when saving the draft`
            : pending
              ? "file uploaded, waiting for approval before it can be attached"
              : "upload the MSA under Details and approve it to attach it"}
        </CheckRow>
      )}
      {approved
        .filter((a) => a.kind !== "msa")
        .map((a) => (
          <CheckRow key={a.id} state="done" label={ARTIFACT_KIND[a.kind]}>
            {a.filename} approved{a.invoice_refs.length > 0 && ` for ${a.invoice_refs.join(", ")}`}: can be attached
          </CheckRow>
        ))}
    </ul>
  )
}

/** Deck AR screen 4, where the case hands over: approved promises feed the Treasury forecast,
 *  and the cash itself is applied in Bank-to-Invoice. QuickBooks balances don't move before. */
export function ArHandover({ c }: { c: CaseDetail }) {
  const s = c.state as ArState
  const cur = s.currency
  const approved = c.commitments.filter((x) => x.status === "approved")
  const total = approved.reduce((t, x) => t + Number(x.amount), 0)
  const bank = c.related_cases.filter((r) => r.workflow === "bank_recon")
  return (
    <Card title="Handover" hint="A promise changes nothing in QuickBooks: the balance drops only when the cash is applied and verified.">
      <ul className="divide-y text-xs">
        <CheckRow state={approved.length ? "done" : "waiting"} label="Treasury">
          {approved.length
            ? `${approved.length} approved promise(s), ${money(total, cur)}, feed the 13-week cash forecast`
            : "Nothing yet: only approved promises with a date feed the forecast"}
        </CheckRow>
        <CheckRow state={bank.some((r) => r.status === "completed") ? "done" : bank.length ? "waiting" : "na"} label="Bank">
          {bank.length === 0 ? (
            <>
              No receipt from this customer yet. When the cash clears it's applied in{" "}
              <Link to="/pod/bank" className="text-primary hover:underline">
                Unapplied cash
              </Link>
            </>
          ) : (
            bank.map((r) => (
              <span key={r.id} className="mr-3 inline-flex flex-wrap items-center gap-1">
                <Link to={`/pod/cases/${r.id}`} className="font-semibold text-primary hover:underline">
                  {r.reference}
                </Link>
                <Pill label={CASE_STATUS[r.status][0]} tone={CASE_STATUS[r.status][1]} />
                {r.summary}
              </span>
            ))
          )}
        </CheckRow>
      </ul>
    </Card>
  )
}


/** Deck AR screen 4: promise dates and the Finance Admin checklist. */
export function ArFollowThrough({ c }: { c: CaseDetail }) {
  const s = c.state as ArState
  const cur = s.currency
  const live = c.commitments.filter((x) => x.status !== "rejected")
  const docTasks = c.review_tasks.filter((t) => t.requirement?.type === "document")
  const sentArtifacts = new Set(c.messages.filter((m) => m.status === "sent").flatMap((m) => m.artifact_ids))
  const dated = live.filter((x) => x.status === "approved" && x.expected_date)
  const reply = [...c.messages].reverse().find((m) => m.direction === "outbound" && m.purpose === "follow_up")
  return (
    <Card title="Follow-through" hint="Promise dates and what the Finance Admin checks. Nothing is booked from a promise.">
      {dated.length > 0 && (
        <div className="mb-3 flex flex-wrap items-center gap-2 text-xs">
          <span className="text-muted-foreground">Promise dates:</span>
          {dated.map((x) => {
            const days = daysUntil(x.expected_date!)
            return (
              <Pill
                key={x.id}
                label={`${x.invoice_number} ${money(x.amount, cur)} · ${promiseLabel({ state: days < 0 ? "overdue" : "upcoming", days_until: days })}`}
                tone={days < 0 ? "bad" : days <= 2 ? "warn" : "info"}
              />
            )
          })}
          <Link to="/pod/ar" className="text-primary hover:underline">
            cash received? see Portfolio
          </Link>
        </div>
      )}

      <div className="rounded-md bg-secondary/40 p-3 text-sm">
        <p className="font-semibold text-brand-navy">Finance Admin checklist</p>
        <ul className="mt-1 divide-y text-xs">
          {docTasks.length === 0 ? (
            <CheckRow state="na" label="Documents">
              None requested by the customer
            </CheckRow>
          ) : (
            docTasks.map((t) => {
              const kind = (t.requirement?.kind ?? "other") as keyof typeof ARTIFACT_KIND
              const label = ARTIFACT_KIND[kind] ?? kind
              const approved = c.artifacts.find(
                (a) => a.kind === kind && a.status === "approved" && (!t.requirement?.invoice || a.invoice_refs.includes(t.requirement.invoice)),
              )
              return (
                <CheckRow key={t.id} state={t.status === "resolved" ? "done" : "waiting"} label={label}>
                  {t.requirement?.invoice ?? "Case"}:{" "}
                  {approved ? (sentArtifacts.has(approved.id) ? "approved and sent" : "approved, not sent yet") : "requested"}
                </CheckRow>
              )
            })
          )}
          <CheckRow state="na" label="Manual QB posting">
            Not applicable: nothing is booked from a promise
          </CheckRow>
          <CheckRow state={reply ? (reply.status === "sent" ? "done" : "waiting") : "na"} label="Proposed response">
            {reply
              ? `${reply.subject}: ${MESSAGE_STATUS[reply.status][0].toLowerCase()}`
              : "No follow-up drafted"}
          </CheckRow>
        </ul>
      </div>
    </Card>
  )
}
