import { useState } from "react"
import { Link, useParams } from "react-router"
import { CircleAlert, CircleCheck, CircleHelp, Download, Gavel, RefreshCw, Send, XCircle } from "lucide-react"

import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { AiBadge, AiCard, Card, Field, GuardedButton, LoadError, Loading, Pill } from "@/features/service-pod/components/bits"
import { formatDateTime } from "@/features/service-pod/labels"
import { attempt } from "@/features/service-pod/ui"
import { cn } from "@/lib/utils"

import { clientsApi, type Application, type ClientCheck, type CreditProposal } from "./clients-api"
import { FpodPage } from "./components/fpod-page"
import { useClientApplication, useFpodMutation } from "./hooks"
import { APPLICATION_STATUS, DOC_KIND, money, RISK, termsText } from "./labels"

const CHECK_ICON: Record<ClientCheck["status"], { icon: typeof XCircle; className: string }> = {
  pass: { icon: CircleCheck, className: "text-emerald-700" },
  fail: { icon: XCircle, className: "text-red-700 dark:text-red-400" },
  warn: { icon: CircleAlert, className: "text-amber-800 dark:text-amber-300" },
  unknown: { icon: CircleHelp, className: "text-muted-foreground" },
}

function Entered({ a }: { a: Application }) {
  const rows: [string, string | null][] = [
    ["Legal name", a.legal_name],
    ["Tax ID", a.tax_id],
    ["Country", a.country],
    ["Address", a.address],
    ["Phone", a.phone],
    ["Website", a.website],
    ["Billing email", a.billing_email],
    ["Currency", a.currency],
    ["Credit limit requested", a.requested_limit ? money(a.requested_limit, a.currency) : null],
    ["Terms requested", a.requested_terms],
    ["Expected monthly spend", a.expected_monthly ? money(a.expected_monthly, a.currency) : null],
    ["Years trading", a.years_trading === null ? null : String(a.years_trading)],
  ]
  return (
    <Card title="What the client entered" hint={`On the secure portal${a.submissions > 1 ? `, ${a.submissions} submissions` : ""}.`}>
      <dl className="grid gap-x-4 gap-y-1.5 text-sm sm:grid-cols-2">
        {rows.map(([k, v]) => (
          <div key={k}>
            <dt className="text-xs text-muted-foreground">{k}</dt>
            <dd className="font-medium break-words">{v ?? "—"}</dd>
          </div>
        ))}
      </dl>
      {a.contacts.length > 0 && (
        <div className="mt-3">
          <p className="text-xs text-muted-foreground">Contacts</p>
          <ul className="text-sm">
            {a.contacts.map((c) => (
              <li key={c.email}>
                {c.name} · {c.email}
                {c.role && ` · ${c.role}`}
                {c.phone && ` · ${c.phone}`}
              </li>
            ))}
          </ul>
        </div>
      )}
      {a.documents.length > 0 && (
        <ul className="mt-3 space-y-0.5 text-sm">
          {a.documents.map((d) => (
            <li key={d.id}>
              <Button size="sm" variant="ghost" onClick={() => clientsApi.downloadDocument(a.id, d)}>
                <Download aria-hidden /> {DOC_KIND[d.kind]}: {d.filename}
              </Button>
            </li>
          ))}
        </ul>
      )}
    </Card>
  )
}

function Checks({ a }: { a: Application }) {
  const clear = useFpodMutation(clientsApi.clear)
  const recheck = useFpodMutation(clientsApi.recheck)
  const [noteFor, setNoteFor] = useState<string | null>(null)
  const [note, setNote] = useState("")
  const cleared = new Map(a.cleared.map((c) => [c.key, c]))
  return (
    <AiCard
      title="Onboarding agent"
      hint={`read and validated the documents and screened sanctions${a.agent_ran_at ? ` (${formatDateTime(a.agent_ran_at)})` : ""}.`}
      badge={<AiBadge label="AI agent" />}
      actions={
        ["submitted", "proposed"].includes(a.status) && (
          <Button size="sm" variant="outline" disabled={recheck.isPending} onClick={() => attempt(() => recheck.mutateAsync([a.id]), "Re-checked.")}>
            <RefreshCw aria-hidden /> Re-check
          </Button>
        )
      }
    >
      {a.checks.length === 0 ? (
        <p className="text-sm text-muted-foreground">Waiting for the client's application.</p>
      ) : (
        <ul className="space-y-2 text-sm">
          {a.checks.map((c) => {
            const { icon: Icon, className } = CHECK_ICON[c.status]
            const done = cleared.get(c.key)
            return (
              <li key={c.key} className="border-b border-border/50 pb-2">
                <p className={cn("flex items-start gap-1.5", done ? "text-muted-foreground" : className)}>
                  <Icon className="mt-0.5 size-4 shrink-0" aria-hidden />
                  <span>
                    <strong>{c.label}</strong>: {c.detail}
                  </span>
                </p>
                {c.gap && a.status === "needs_info" && <p className="ml-6 text-xs text-sky-800">Sent to the client: {c.gap}</p>}
                {done && (
                  <p className="ml-6 text-xs text-emerald-700">
                    Cleared by {done.by}: {done.note}
                  </p>
                )}
                {!done && c.status !== "pass" && c.clearable && a.status === "submitted" && (
                  <div className="mt-1 ml-6">
                    {noteFor === c.key ? (
                      <div className="flex gap-2">
                        <Input value={note} onChange={(e) => setNote(e.target.value)} placeholder="Why it's fine (what you checked)" />
                        <Button
                          size="sm"
                          disabled={clear.isPending || note.trim().length < 5}
                          onClick={async () => {
                            const ok = await attempt(() => clear.mutateAsync([a.id, c.key, note.trim()]), "Cleared.")
                            if (ok) {
                              setNoteFor(null)
                              setNote("")
                            }
                          }}
                        >
                          Clear
                        </Button>
                      </div>
                    ) : (
                      <Button size="sm" variant="ghost" onClick={() => setNoteFor(c.key)}>
                        Clear with a note
                      </Button>
                    )}
                  </div>
                )}
              </li>
            )
          })}
        </ul>
      )}
      {(a.extraction?.notes.length ?? 0) > 0 && (
        <p className="mt-2 text-xs text-muted-foreground">Notes: {a.extraction!.notes.join("; ")}</p>
      )}
    </AiCard>
  )
}

function Proposal({ a, p }: { a: Application; p: CreditProposal }) {
  return (
    <AiCard
      title="Credit agent"
      hint={`scored the risk and proposed terms${a.proposed_at ? ` (${formatDateTime(a.proposed_at)})` : ""}. It only proposes: the credit controller decides.`}
      badge={<AiBadge label="AI agent" />}
    >
      <div className="flex flex-wrap items-center gap-3">
        <p className="text-3xl font-semibold tabular-nums">
          {p.score}
          <span className="text-base font-normal text-muted-foreground">/100</span>
        </p>
        <Pill label={RISK[p.risk][0]} tone={RISK[p.risk][1]} />
        <p className="text-sm font-medium">Proposes: {termsText(p, p.currency)}</p>
      </div>
      <table className="mt-3 w-full text-sm">
        <thead className="text-left text-xs text-muted-foreground">
          <tr className="border-b border-border">
            <th className="py-1.5 pr-3 font-medium">Factor</th>
            <th className="py-1.5 pr-3 font-medium">From the data</th>
            <th className="py-1.5 text-right font-medium">Points</th>
          </tr>
        </thead>
        <tbody>
          {p.factors.map((f) => (
            <tr key={f.label} className="border-b border-border/50">
              <td className="py-1.5 pr-3">{f.label}</td>
              <td className="py-1.5 pr-3 text-muted-foreground">{f.value}</td>
              <td className="py-1.5 text-right tabular-nums">
                {f.points} / {f.max}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      <ul className="mt-3 list-disc space-y-0.5 pl-5 text-sm">
        {p.reasons.map((r) => (
          <li key={r}>{r}</li>
        ))}
      </ul>
    </AiCard>
  )
}

function Decide({ a, p }: { a: Application; p: CreditProposal }) {
  const decide = useFpodMutation(clientsApi.decide)
  const [credit, setCredit] = useState(p.decision === "credit")
  const [form, setForm] = useState({
    credit_limit: p.credit_limit ?? "",
    deposit_pct: p.deposit_pct,
    payment_terms: p.payment_terms,
    currency: p.currency,
    note: "",
  })
  const body = { ...form, credit_limit: credit ? form.credit_limit || null : null }
  const changed =
    (body.credit_limit === null ? null : Number(body.credit_limit)) !== (p.credit_limit === null ? null : Number(p.credit_limit)) ||
    Number(body.deposit_pct) !== Number(p.deposit_pct) ||
    body.payment_terms.trim() !== p.payment_terms ||
    body.currency !== p.currency
  return (
    <Card title="Credit controller: approve the terms" hint="Approve as proposed, or change them and say why. No credit is granted without this approval.">
      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <Field label="Account type">
          <div className="flex rounded-lg border border-border p-0.5 text-xs">
            {[true, false].map((v) => (
              <button
                key={String(v)}
                type="button"
                onClick={() => setCredit(v)}
                className={cn("flex-1 rounded-md px-3 py-1.5 font-medium", credit === v ? "bg-primary text-primary-foreground" : "text-muted-foreground")}
              >
                {v ? "Credit" : "Deposit only"}
              </button>
            ))}
          </div>
        </Field>
        {credit && (
          <Field label={`Credit limit (${form.currency})`}>
            <Input inputMode="decimal" value={form.credit_limit} onChange={(e) => setForm({ ...form, credit_limit: e.target.value })} />
          </Field>
        )}
        <Field label="Deposit %">
          <Input inputMode="decimal" value={form.deposit_pct} onChange={(e) => setForm({ ...form, deposit_pct: e.target.value })} />
        </Field>
        <Field label="Payment terms">
          <Input value={form.payment_terms} onChange={(e) => setForm({ ...form, payment_terms: e.target.value })} />
        </Field>
        <Field label="Currency">
          <Input maxLength={3} value={form.currency} onChange={(e) => setForm({ ...form, currency: e.target.value.toUpperCase() })} />
        </Field>
        <div className="sm:col-span-2 lg:col-span-3">
          <Field label={changed ? "Why you changed the proposal (required)" : "Note (optional)"}>
            <Input value={form.note} onChange={(e) => setForm({ ...form, note: e.target.value })} />
          </Field>
        </div>
      </div>
      <GuardedButton
        className="mt-3"
        reason={a.can_decide}
        disabled={decide.isPending || (credit && !form.credit_limit) || (changed && !form.note.trim())}
        onClick={() => attempt(() => decide.mutateAsync([a.id, body]), "Approved: the account agent set up the account.")}
      >
        <Gavel aria-hidden /> Approve {changed ? "with changes" : "as proposed"} and open the account
      </GuardedButton>
    </Card>
  )
}

export function ClientApplicationPage() {
  const { applicationId } = useParams()
  const q = useClientApplication(applicationId)
  const resend = useFpodMutation(clientsApi.resend)
  const ask = useFpodMutation(clientsApi.requestInfo)
  const reject = useFpodMutation(clientsApi.reject)
  const a = q.data
  return (
    <FpodPage title={a ? `Client: ${a.client_name}` : "Client application"}>
      {q.isPending ? (
        <Loading what="the application" />
      ) : q.isError || !a ? (
        <LoadError what="the application" />
      ) : (
        <div className="space-y-5">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <div className="flex flex-wrap items-center gap-2 text-sm">
              <Link to="/finance-pod/clients" className="text-primary hover:underline">
                ← Client accounts
              </Link>
              <span className="text-muted-foreground">{a.reference}</span>
              <Pill label={APPLICATION_STATUS[a.status][0]} tone={APPLICATION_STATUS[a.status][1]} />
              <span className="text-xs text-muted-foreground">
                opened by {a.invited_by_name} · {a.client_email}
              </span>
            </div>
            <div className="flex flex-wrap gap-2">
              {["invited", "needs_info"].includes(a.status) && (
                <Button size="sm" variant="outline" disabled={resend.isPending} onClick={() => attempt(() => resend.mutateAsync([a.id]), "A new link was sent.")}>
                  <Send aria-hidden /> Send a new link
                </Button>
              )}
              {["submitted", "proposed"].includes(a.status) && (
                <Button
                  size="sm"
                  variant="outline"
                  disabled={ask.isPending}
                  onClick={() => {
                    const reason = window.prompt("What should the client send or correct? (the agent's gaps are included)")
                    if (reason?.trim()) void attempt(() => ask.mutateAsync([a.id, reason.trim()]), "Sent to the client with a new link.")
                  }}
                >
                  Ask the client for more
                </Button>
              )}
              {!["active", "rejected"].includes(a.status) && (
                <Button
                  size="sm"
                  variant="ghost"
                  disabled={reject.isPending}
                  onClick={() => {
                    const reason = window.prompt("Why reject this application?")
                    if (reason?.trim()) void attempt(() => reject.mutateAsync([a.id, reason.trim()]), "Rejected.")
                  }}
                >
                  Reject
                </Button>
              )}
            </div>
          </div>

          {a.portal_url && (
            <p className="rounded-md bg-muted/40 px-3 py-2 text-xs break-all">
              Link sent (shown once): <a className="text-primary underline" href={a.portal_url}>{a.portal_url}</a>
            </p>
          )}
          {a.status === "needs_info" && a.gaps.length > 0 && (
            <div className="rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 text-sm text-amber-950">
              <p className="font-medium">The onboarding agent sent the client what's missing, with a new link:</p>
              <ul className="mt-1 list-disc pl-5">
                {a.gaps.map((g) => (
                  <li key={g}>{g}</li>
                ))}
              </ul>
            </div>
          )}
          {a.status === "active" && (
            <p className="rounded-lg border border-emerald-200 bg-emerald-50 px-3 py-2 text-sm text-emerald-900">
              Approved by {a.decided_by_name} {a.decided_at && formatDateTime(a.decided_at)}
              {a.changed_from_proposal && ` (changed from the proposal: ${a.decision_note})`}. Account{" "}
              {a.client_id ? (
                <Link to={`/finance-pod/clients/${a.client_id}`} className="font-medium underline">
                  {a.client_code}
                </Link>
              ) : (
                a.client_code
              )}{" "}
              is open in the ERP and the lab system.
            </p>
          )}
          {a.rejected_reason && <p className="text-sm text-red-700">Rejected: {a.rejected_reason}</p>}

          <div className="grid gap-5 xl:grid-cols-2">
            <Entered a={a} />
            <Checks a={a} />
          </div>
          {a.proposal && <Proposal a={a} p={a.proposal} />}
          {a.status === "proposed" && a.proposal && <Decide key={a.proposed_at} a={a} p={a.proposal} />}
        </div>
      )}
    </FpodPage>
  )
}
