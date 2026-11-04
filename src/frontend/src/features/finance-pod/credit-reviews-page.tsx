import { useState } from "react"
import { Link } from "react-router"
import { Activity, ArrowRight, Check, X } from "lucide-react"

import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { AiBadge, AiCard, Empty, Field, LoadError, Loading, Pill } from "@/features/service-pod/components/bits"
import { formatDateTime } from "@/features/service-pod/labels"
import { attempt, selectClass } from "@/features/service-pod/ui"
import { cn } from "@/lib/utils"

import { clientsApi, type CreditReview, type ReviewTerms } from "./clients-api"
import { FpodPage } from "./components/fpod-page"
import { useCreditReviews, useFpodMutation } from "./hooks"
import { REVIEW_STATUS, termsText } from "./labels"

function TermsLine({ t, currency }: { t: ReviewTerms; currency: string }) {
  return (
    <span>
      {termsText(t, currency)}
      {t.status === "on_hold" && <strong className="text-red-700"> · on hold</strong>}
    </span>
  )
}

function Review({ r }: { r: CreditReview }) {
  const decide = useFpodMutation(clientsApi.decideReview)
  const [changing, setChanging] = useState(false)
  const p = r.proposal.proposed
  const [form, setForm] = useState({
    credit_limit: p.credit_limit ?? "",
    deposit_pct: p.deposit_pct,
    payment_terms: p.payment_terms,
    status: p.status,
    note: "",
  })
  const m = r.proposal.metrics
  const open = r.status === "proposed"
  return (
    <AiCard
      title={`${r.reference} · ${r.client_code} ${r.client_name}`}
      hint={`${r.trigger === "periodic" ? "periodic review" : "as history built"}, ${formatDateTime(r.created_at)}`}
      badge={<AiBadge label="Monitor" />}
      actions={<Pill label={REVIEW_STATUS[r.status][0]} tone={REVIEW_STATUS[r.status][1]} />}
    >
      <ul className="list-disc space-y-0.5 pl-5 text-sm">
        {r.proposal.reasons.map((x) => (
          <li key={x}>{x}</li>
        ))}
      </ul>
      <p className="mt-3 flex flex-wrap items-center gap-2 text-sm">
        <span className="text-muted-foreground">Now:</span> <TermsLine t={r.proposal.current} currency={r.currency} />
        <ArrowRight className="size-4 text-muted-foreground" aria-hidden />
        <span className="font-semibold">
          <TermsLine t={p} currency={r.currency} />
        </span>
      </p>
      <p className="mt-1 text-xs text-muted-foreground">
        {m.invoices} invoice(s) over {m.months} months · {m.on_time_rate === null ? "no payments yet" : `${Math.round(m.on_time_rate * 100)}% paid on time`}
        {m.overdue > 0 && ` · ${m.overdue} overdue`}
      </p>
      {open ? (
        <div className="mt-3 space-y-2">
          {changing && (
            <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-4">
              <Field label="Credit limit (blank: deposit only)">
                <Input inputMode="decimal" value={form.credit_limit} onChange={(e) => setForm({ ...form, credit_limit: e.target.value })} />
              </Field>
              <Field label="Deposit %">
                <Input inputMode="decimal" value={form.deposit_pct} onChange={(e) => setForm({ ...form, deposit_pct: e.target.value })} />
              </Field>
              <Field label="Payment terms">
                <Input value={form.payment_terms} onChange={(e) => setForm({ ...form, payment_terms: e.target.value })} />
              </Field>
              <Field label="Status">
                <select className={selectClass} value={form.status} onChange={(e) => setForm({ ...form, status: e.target.value as ReviewTerms["status"] })}>
                  <option value="active">Active</option>
                  <option value="on_hold">On hold</option>
                </select>
              </Field>
            </div>
          )}
          <Field label={changing ? "Why you changed the proposal (required)" : "Note (optional)"}>
            <Input value={form.note} onChange={(e) => setForm({ ...form, note: e.target.value })} />
          </Field>
          <div className="flex flex-wrap gap-2">
            <Button
              size="sm"
              disabled={decide.isPending || (changing && !form.note.trim())}
              onClick={() =>
                attempt(
                  () =>
                    decide.mutateAsync([
                      r.id,
                      {
                        approve: true,
                        note: form.note,
                        status: changing ? form.status : null,
                        terms: changing
                          ? { credit_limit: form.credit_limit || null, deposit_pct: form.deposit_pct, payment_terms: form.payment_terms, currency: r.currency }
                          : null,
                      },
                    ]),
                  "Approved: updated in the ERP and the lab system.",
                )
              }
            >
              <Check aria-hidden /> Approve{changing ? " with changes" : ""}
            </Button>
            <Button size="sm" variant="outline" onClick={() => setChanging((v) => !v)}>
              {changing ? "Use the proposal" : "Change the terms"}
            </Button>
            <Button
              size="sm"
              variant="ghost"
              disabled={decide.isPending}
              onClick={() => attempt(() => decide.mutateAsync([r.id, { approve: false, note: form.note }]), "Dismissed: the terms stay as they are.")}
            >
              <X aria-hidden /> Dismiss
            </Button>
          </div>
        </div>
      ) : (
        <p className="mt-2 text-xs text-muted-foreground">
          {REVIEW_STATUS[r.status][0]} by {r.decided_by_name} {r.decided_at && formatDateTime(r.decided_at)}
          {r.decision_note && `: ${r.decision_note}`}
        </p>
      )}
    </AiCard>
  )
}

export function CreditReviewsPage() {
  const [openOnly, setOpenOnly] = useState(true)
  const list = useCreditReviews(openOnly)
  return (
    <FpodPage title="Credit reviews" subtitle="The monitor reviews each account as history builds and at its periodic review; the credit controller decides.">
      <div className="space-y-4">
        <div className="flex items-center justify-between gap-2">
          <div className="flex rounded-lg border border-border p-0.5 text-xs">
            {[true, false].map((v) => (
              <button
                key={String(v)}
                type="button"
                onClick={() => setOpenOnly(v)}
                className={cn("rounded-md px-3 py-1 font-medium", openOnly === v ? "bg-primary text-primary-foreground" : "text-muted-foreground")}
              >
                {v ? "Waiting" : "All"}
              </button>
            ))}
          </div>
          <Link to="/finance-pod/clients" className="text-sm text-primary hover:underline">
            Client accounts
          </Link>
        </div>
        {list.isPending ? (
          <Loading what="credit reviews" />
        ) : list.isError ? (
          <LoadError what="credit reviews" />
        ) : list.data.length === 0 ? (
          <Empty icon={<Activity className="size-5" />}>
            {openOnly ? "No review is waiting. Run the monitor or import billing history on Client accounts." : "No reviews yet."}
          </Empty>
        ) : (
          list.data.map((r) => <Review key={r.id} r={r} />)
        )}
      </div>
    </FpodPage>
  )
}
