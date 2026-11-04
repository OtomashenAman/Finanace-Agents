import { useState } from "react"
import { Link, useParams } from "react-router"
import { CircleAlert, CircleCheck, CircleHelp, Download, PhoneCall, RefreshCw, ShieldCheck, XCircle } from "lucide-react"

import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { AiBadge, AiCard, Card, Field, GuardedButton, LoadError, Loading, Pill } from "@/features/service-pod/components/bits"
import { formatDateTime } from "@/features/service-pod/labels"
import { attempt, selectClass } from "@/features/service-pod/ui"
import { cn } from "@/lib/utils"

import { FpodPage } from "./components/fpod-page"
import { useFpodMutation, useOnboarding } from "./hooks"
import { ONBOARDING_STATUS } from "./labels"
import { CALLBACK_SOURCES, procurementApi, type Check, type Onboarding } from "./procurement-api"

const CHECK_ICON: Record<Check["status"], { icon: typeof XCircle; className: string }> = {
  pass: { icon: CircleCheck, className: "text-emerald-700" },
  fail: { icon: XCircle, className: "text-red-700 dark:text-red-400" },
  warn: { icon: CircleAlert, className: "text-amber-800 dark:text-amber-300" },
  unknown: { icon: CircleHelp, className: "text-muted-foreground" },
}

function Checks({ o }: { o: Onboarding }) {
  const clear = useFpodMutation(procurementApi.clear)
  const recheck = useFpodMutation(procurementApi.recheck)
  const [noteFor, setNoteFor] = useState<string | null>(null)
  const [note, setNote] = useState("")
  const cleared = new Map(o.cleared.map((c) => [c.key, c]))
  return (
    <AiCard
      title="Onboarding agent"
      hint={`read the tax form and bank letter, validated the tax ID and screened sanctions${o.agent_ran_at ? ` (${formatDateTime(o.agent_ran_at)})` : ""}.`}
      badge={<AiBadge label="AI agent" />}
      actions={
        o.status === "submitted" && (
          <Button size="sm" variant="outline" disabled={recheck.isPending} onClick={() => attempt(() => recheck.mutateAsync([o.id]), "Re-checked.")}>
            <RefreshCw aria-hidden /> Re-check
          </Button>
        )
      }
    >
      {o.checks.length === 0 ? (
        <p className="text-sm text-muted-foreground">Waiting for the vendor's form.</p>
      ) : (
        <ul className="space-y-2 text-sm">
          {o.checks.map((c) => {
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
                {done && (
                  <p className="ml-6 text-xs text-emerald-700">
                    Cleared by {done.by}: {done.note}
                  </p>
                )}
                {!done && c.status !== "pass" && c.clearable && o.status === "submitted" && (
                  <div className="ml-6 mt-1">
                    {noteFor === c.key ? (
                      <div className="flex gap-2">
                        <Input value={note} onChange={(e) => setNote(e.target.value)} placeholder="Why it's fine (what you checked)" />
                        <Button
                          size="sm"
                          disabled={clear.isPending || note.trim().length < 5}
                          onClick={async () => {
                            const ok = await attempt(() => clear.mutateAsync([o.id, c.key, note.trim()]), "Cleared.")
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
                {!c.clearable && c.status === "fail" && (
                  <p className="ml-6 text-xs text-muted-foreground">Can't be cleared: the details disagree. Use "Ask the vendor to resubmit" (or reject).</p>
                )}
              </li>
            )
          })}
        </ul>
      )}
    </AiCard>
  )
}

function Callback({ o }: { o: Onboarding }) {
  const verify = useFpodMutation(procurementApi.verify)
  const [form, setForm] = useState({ phone: "", source: CALLBACK_SOURCES[0], contact: "", confirmed_last4: "", notes: "" })
  return (
    <Card
      title="AP analyst: call back to confirm the bank"
      hint="Call a number you already hold or find independently, never the one the vendor just gave. Ask them to read the account's last four digits."
    >
      <div className="grid gap-2 sm:grid-cols-2">
        <Field label="Number you called">
          <Input value={form.phone} onChange={(e) => setForm({ ...form, phone: e.target.value })} />
        </Field>
        <Field label="Where the number came from">
          <select className={selectClass} value={form.source} onChange={(e) => setForm({ ...form, source: e.target.value })}>
            {CALLBACK_SOURCES.map((s) => (
              <option key={s}>{s}</option>
            ))}
          </select>
        </Field>
        <Field label="Who you spoke to">
          <Input value={form.contact} onChange={(e) => setForm({ ...form, contact: e.target.value })} />
        </Field>
        <Field label="Last 4 digits they confirmed">
          <Input inputMode="numeric" maxLength={4} value={form.confirmed_last4} onChange={(e) => setForm({ ...form, confirmed_last4: e.target.value })} />
        </Field>
        <div className="sm:col-span-2">
          <Field label="Notes">
            <Input value={form.notes} onChange={(e) => setForm({ ...form, notes: e.target.value })} />
          </Field>
        </div>
      </div>
      <GuardedButton
        className="mt-3"
        reason={o.can_verify}
        disabled={verify.isPending || !form.phone || !form.contact || form.confirmed_last4.length !== 4}
        onClick={() => attempt(() => verify.mutateAsync([o.id, form]), "Bank details verified.")}
      >
        <PhoneCall aria-hidden /> Record call-back and verify
      </GuardedButton>
    </Card>
  )
}

export function VendorPage() {
  const { onboardingId } = useParams()
  const ob = useOnboarding(onboardingId)
  const activate = useFpodMutation(procurementApi.activate)
  const reject = useFpodMutation(procurementApi.reject)
  const resend = useFpodMutation(procurementApi.resend)
  const resubmit = useFpodMutation(procurementApi.requestResubmission)
  const o = ob.data
  return (
    <FpodPage title={o ? `Vendor: ${o.vendor_name}` : "Vendor onboarding"}>
      {ob.isPending ? (
        <Loading what="the onboarding" />
      ) : ob.isError || !o ? (
        <LoadError what="the onboarding" />
      ) : (
        <div className="space-y-5">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <div className="flex items-center gap-2 text-sm">
              <Link to="/finance-pod/vendors" className="text-primary hover:underline">
                ← All vendors
              </Link>
              <Pill label={ONBOARDING_STATUS[o.status][0]} tone={ONBOARDING_STATUS[o.status][1]} />
              {o.kind === "bank_change" && <Pill label="bank change" tone="warn" />}
              {o.request_reference && o.request_id && (
                <Link to={`/finance-pod/requests/${o.request_id}`} className="text-primary hover:underline">
                  for {o.request_reference}
                </Link>
              )}
            </div>
            <div className="flex flex-wrap gap-2">
              {o.status === "invited" && (
                <Button size="sm" variant="outline" disabled={resend.isPending} onClick={() => attempt(() => resend.mutateAsync([o.id]), "A new link was sent.")}>
                  Send a new link
                </Button>
              )}
              {o.status === "submitted" && (
                <Button
                  size="sm"
                  variant="outline"
                  disabled={resubmit.isPending}
                  onClick={() => {
                    const reason = window.prompt(
                      "What should the vendor fix? (e.g. the tax ID must be 9 digits; upload your signed W-9 and a bank letter)",
                    )
                    if (reason?.trim())
                      void attempt(() => resubmit.mutateAsync([o.id, reason.trim()]), "A new link was sent to the vendor.")
                  }}
                >
                  Ask the vendor to resubmit
                </Button>
              )}
              {o.status === "verified" && (
                <GuardedButton
                  reason={o.can_activate}
                  disabled={activate.isPending}
                  onClick={() => attempt(() => activate.mutateAsync([o.id]), "Vendor activated.")}
                >
                  <ShieldCheck aria-hidden /> Activate vendor (second approver)
                </GuardedButton>
              )}
              {!["active", "rejected"].includes(o.status) && (
                <Button
                  size="sm"
                  variant="ghost"
                  disabled={reject.isPending}
                  onClick={() => {
                    const reason = window.prompt("Why reject this vendor submission?")
                    if (reason?.trim()) void attempt(() => reject.mutateAsync([o.id, reason.trim()]), "Rejected.")
                  }}
                >
                  Reject
                </Button>
              )}
            </div>
          </div>

          {o.portal_url && (
            <p className="rounded-md bg-muted/40 px-3 py-2 text-xs break-all">
              Portal link (shown once): <a className="text-primary underline" href={o.portal_url}>{o.portal_url}</a>
            </p>
          )}
          {o.status === "verified" && o.can_activate && <p className="text-sm text-muted-foreground">{o.can_activate}</p>}
          {o.status === "active" && (
            <p className="rounded-lg border border-emerald-200 bg-emerald-50 px-3 py-2 text-sm text-emerald-900">
              Active as {o.vendor_code} (ERP ref {o.erp_ref}), activated by {o.activated_by_name} {formatDateTime(o.activated_at!)}
              ; verified by {o.verified_by_name}.
            </p>
          )}
          {o.rejected_reason && <p className="text-sm text-red-700">Rejected: {o.rejected_reason}</p>}

          <div className="grid gap-5 xl:grid-cols-2">
            <Card title="What the vendor entered" hint="Through the secure portal. Account and routing numbers are stored encrypted; only the last four show.">
              <dl className="grid gap-1 text-sm sm:grid-cols-2">
                {(
                  [
                    ["Legal name", o.legal_name],
                    ["Tax form", o.tax_form],
                    ["Tax ID", o.tax_id],
                    ["Address", o.address],
                    ["Phone (not for the call-back)", o.phone],
                    ["Bank", o.bank_name],
                    ["Account holder", o.account_name],
                    ["Routing", o.routing_masked],
                    ["Account", o.account_masked],
                  ] as [string, string | null][]
                ).map(([k, v]) => (
                  <div key={k}>
                    <dt className="text-xs text-muted-foreground">{k}</dt>
                    <dd className="font-medium">{v ?? "—"}</dd>
                  </div>
                ))}
              </dl>
              {o.documents.length > 0 && (
                <ul className="mt-3 space-y-1 text-sm">
                  {o.documents.map((d) => (
                    <li key={d.id}>
                      <Button size="sm" variant="ghost" onClick={() => procurementApi.downloadDocument(o.id, d)}>
                        <Download aria-hidden /> {d.kind.replace("_", " ")}: {d.filename}
                      </Button>
                    </li>
                  ))}
                </ul>
              )}
            </Card>
            <Checks o={o} />
          </div>
          {o.status === "submitted" && <Callback o={o} />}
          {o.verified_at && (
            <Card title="Call-back">
              <p className="text-sm">
                {o.verified_by_name} called {o.callback_phone} ({o.callback_source}) and spoke to {o.callback_contact},{" "}
                {formatDateTime(o.verified_at)}. {o.callback_notes}
              </p>
            </Card>
          )}
        </div>
      )}
    </FpodPage>
  )
}
