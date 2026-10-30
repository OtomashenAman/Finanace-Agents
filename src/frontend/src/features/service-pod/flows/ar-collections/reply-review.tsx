import { useState, type ReactNode } from "react"
import { Bot, CalendarClock, CircleAlert, FileCheck2 } from "lucide-react"

import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"

import type { CaseDetail, Message, ReviewTask } from "../../api"
import { Pill } from "../../components/bits"
import { Extraction } from "../../components/case-messages"
import { useCompose, useCreateDraft, useDecideArtifact, useUploadArtifact } from "../../hooks"
import { ARTIFACT_KIND, CASE_STATUS } from "../../labels"
import { attempt } from "../../ui"
import { useRunAction } from "../../use-run-action"
import { money, type InvoiceState } from "../shared"

/** What the AI returned for an AR reply (ArReplyRead on the backend) */
interface ArReading {
  intent: string
  tranches: { invoice_number: string; amount: string; date: string | null; quote: string; confidence: number }[]
  disputes: { invoice_number: string; amount: string | null; reason: string; quote: string }[]
  document_requests: { kind: string; invoice_numbers: string[]; quote: string }[]
  unclear: string[]
}

const MIN_CONFIDENCE = 0.8 // same threshold as the backend's reading rules

function Row({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="grid grid-cols-[92px_1fr] gap-2 py-1">
      <dt className="text-muted-foreground">{label}</dt>
      <dd>{children}</dd>
    </div>
  )
}

/** Approve the requested document: the preparer uploads it, a reviewer approves it, and the
 *  matching review task then settles itself. */
function DocumentButton({ c, task }: { c: CaseDetail; task: ReviewTask }) {
  const upload = useUploadArtifact()
  const decide = useDecideArtifact()
  const kind = (task.requirement?.kind ?? "other") as keyof typeof ARTIFACT_KIND
  const invoice = task.requirement?.invoice ?? ""
  const label = ARTIFACT_KIND[kind] ?? kind
  const pending = c.artifacts.find((a) => a.kind === kind && a.status === "pending" && (!invoice || a.invoice_refs.includes(invoice)))
  if (c.my_roles.includes("reviewer") && pending) {
    return (
      <Button
        size="sm"
        disabled={decide.isPending}
        onClick={() => void attempt(() => decide.mutateAsync({ id: pending.id, decision: "approved" }), `${label} approved.`)}
      >
        <FileCheck2 /> Approve {label.toLowerCase()}
      </Button>
    )
  }
  if (c.my_roles.includes("owner")) {
    return (
      <label className="inline-flex cursor-pointer items-center gap-2 rounded-md border px-3 py-1.5 text-sm font-medium hover:bg-secondary">
        <FileCheck2 className="size-4" aria-hidden /> Upload {label.toLowerCase()}
        {invoice && ` for ${invoice}`}
        <input
          type="file"
          className="sr-only"
          onChange={(e) => {
            const file = e.target.files?.[0]
            if (file) void attempt(() => upload.mutateAsync({ caseId: c.id, file, kind, invoiceRefs: invoice }), "Uploaded: a reviewer approves it.")
            e.target.value = ""
          }}
        />
      </label>
    )
  }
  return (
    <span className="text-xs text-muted-foreground" title="The preparer uploads it, a reviewer approves it">
      {pending ? `${label} waiting for a reviewer` : `${label} not uploaded yet`}
    </span>
  )
}

/** A follow-up draft asking for the missing date (figures stay locked to the source). */
function AskForDate({ c, tasks }: { c: CaseDetail; tasks: ReviewTask[] }) {
  const compose = useCompose()
  const create = useCreateDraft()
  const undated = c.commitments.filter((x) => x.status === "proposed" && !x.expected_date)
  const question = undated.length
    ? `Could you please confirm the payment date for ${undated
        .map((x) => `${money(x.amount, (c.state as { currency?: string }).currency)} on ${x.invoice_number}`)
        .join(" and ")}?`
    : `Could you please confirm the payment date for ${tasks.map((t) => t.subject).filter(Boolean).join(", ") || "the invoices below"}?`
  return (
    <Button
      size="sm"
      variant="outline"
      disabled={compose.isPending || create.isPending}
      onClick={() =>
        void attempt(async () => {
          const d = await compose.mutateAsync({ caseId: c.id, purpose: "follow_up" })
          const body = d.fact_block ? d.body.replace(d.fact_block, `${question}\n\n${d.fact_block}`) : `${question}\n\n${d.body}`
          return create.mutateAsync({
            caseId: c.id,
            draft: { audience: "customer", purpose: "follow_up", to_email: d.to_email ?? "", to_name: d.to_name, subject: d.subject, body, artifact_ids: [] },
          })
        }, "Follow-up drafted below: a reviewer approves it before it's sent.")
      }
    >
      <CalendarClock /> Ask for date
    </Button>
  )
}

function Escalate({ c }: { c: CaseDetail }) {
  const { run, pending } = useRunAction(c)
  const [open, setOpen] = useState(false)
  const [why, setWhy] = useState("")
  if (!open)
    return (
      <Button size="sm" variant="outline" onClick={() => setOpen(true)}>
        <CircleAlert /> Escalate
      </Button>
    )
  return (
    <span className="flex w-full gap-2">
      <Input className="h-9" placeholder="What the reviewer must decide" value={why} onChange={(e) => setWhy(e.target.value)} />
      <Button
        size="sm"
        disabled={pending || why.trim().length < 3}
        onClick={() =>
          void run("add_review_task", { kind: "ambiguity", subject: "Escalated", detail: why, blocking: true }, "Escalated to the reviewer.").then(
            (r) => r && setOpen(false),
          )
        }
      >
        Raise
      </Button>
    </span>
  )
}

/** Deck AR screen 3: the reply next to what the AI read, the checks on it and the next steps. */
export function ArReplyReview({ c, m }: { c: CaseDetail; m: Message }) {
  const reading = m.extraction?.output as unknown as ArReading | undefined
  if (m.extraction_status !== "done" || !reading) return <Extraction m={m} />

  const state = c.state as { currency?: string; invoices?: (InvoiceState & { original_amount?: string })[] }
  const open = c.review_tasks.filter((t) => t.status === "open")
  const docTasks = open.filter((t) => t.requirement?.type === "document")
  const dateTasks = open.filter((t) => t.kind === "unknown_date")
  const unsure = reading.tranches.some((t) => t.confidence < MIN_CONFIDENCE) || open.some((t) => t.kind === "ambiguity")
  // A later reply can date a promise this one made, so match on the case's commitments
  const promises = c.commitments.filter((x) => x.status !== "rejected")
  const caseOpen = !["completed", "rejected", "cancelled"].includes(c.status)
  const canAct = caseOpen && c.my_roles.length > 0

  // Validation is arithmetic on the case's own figures, never the model's
  const validation = (state.invoices ?? [])
    .map((inv) => {
      const promised = c.commitments
        .filter((x) => x.invoice_number === inv.number && x.status !== "rejected")
        .map((x) => Number(x.amount))
      if (!promised.length) return null
      const total = promised.reduce((a, b) => a + b, 0)
      const balance = Number(inv.balance)
      const parts = promised.map((p) => money(p, state.currency)).join(" + ")
      return { number: inv.number, text: `${parts} = ${money(total, state.currency)}`, ok: total <= balance, full: total === balance, balance }
    })
    .filter((v) => v !== null)

  return (
    <div className="rounded-md border border-sky-200 bg-sky-50/50 p-3 text-xs">
      <p className="mb-2 flex flex-wrap items-center gap-1.5">
        <Bot className="size-3.5 text-sky-900" aria-hidden />
        <span className="font-semibold text-sky-900">AI recommendation</span>
        <Pill label={unsure ? "Confidence: review" : "Confidence: ok"} tone={unsure ? "warn" : "good"} />
        <Pill
          label={docTasks.length ? `Proof: ${docTasks.map((t) => ARTIFACT_KIND[(t.requirement?.kind ?? "other") as keyof typeof ARTIFACT_KIND] ?? t.requirement?.kind).join(", ").toLowerCase()} pending` : "Proof: none pending"}
          tone={docTasks.length ? "warn" : "neutral"}
        />
        <Pill label="QB posting: none" tone="neutral" />
        <Pill label={`Case: ${CASE_STATUS[c.status][0].toLowerCase()}`} tone="neutral" />
      </p>
      <dl className="divide-y divide-sky-100">
        <Row label="Intent">{reading.intent || "-"}</Row>
        <Row label="Promises">
          {reading.tranches.length === 0 && "None"}
          <ul className="space-y-0.5">
            {reading.tranches.map((t, i) => {
              const made = promises.find((x) => x.invoice_number === t.invoice_number && Number(x.amount) === Number(t.amount))
              return (
                <li key={i}>
                  <strong>{t.invoice_number}</strong> {money(t.amount, state.currency)} ·{" "}
                  {made?.expected_date ?? t.date ?? <span className="text-amber-800">no date</span>}
                  {!made && <span className="text-amber-800"> · not used (see review tasks)</span>}
                  <span className="block text-muted-foreground italic">“{t.quote}”</span>
                </li>
              )
            })}
          </ul>
        </Row>
        <Row label="Validation">
          {validation.length === 0 && "Nothing promised yet"}
          {validation.map((v) => (
            <p key={v.number} className={v.ok ? "text-emerald-800" : "text-red-800"}>
              {v.number}: {v.text} {v.full ? "= open balance ✓" : v.ok ? `of ${money(v.balance, state.currency)} open` : `exceeds ${money(v.balance, state.currency)} open`}
            </p>
          ))}
        </Row>
        {reading.disputes.length > 0 && (
          <Row label="Disputed">
            {reading.disputes.map((d, i) => (
              <p key={i}>
                <strong>{d.invoice_number}</strong> {d.amount ? money(d.amount, state.currency) : "part"}: {d.reason}
              </p>
            ))}
          </Row>
        )}
        <Row label="Unclear">
          {dateTasks.length + reading.unclear.length === 0 && "Nothing"}
          {dateTasks.map((t) => (
            <p key={t.id}>{t.detail}</p>
          ))}
          {reading.unclear.map((u, i) => (
            <p key={`u${i}`}>{u}</p>
          ))}
        </Row>
        {reading.document_requests.length > 0 && (
          <Row label="Requested">
            {reading.document_requests.map((r, i) => (
              <p key={i}>
                {ARTIFACT_KIND[r.kind as keyof typeof ARTIFACT_KIND] ?? r.kind}
                {r.invoice_numbers.length > 0 && ` for ${r.invoice_numbers.join(", ")}`}
                {docTasks.some((t) => t.requirement?.kind === r.kind) ? " · pending" : " · settled"}
              </p>
            ))}
          </Row>
        )}
      </dl>
      {canAct && (
        <div className="mt-3 flex flex-wrap gap-2 border-t border-sky-100 pt-3">
          {docTasks.map((t) => (
            <DocumentButton key={t.id} c={c} task={t} />
          ))}
          {dateTasks.length > 0 && c.my_roles.includes("owner") && <AskForDate c={c} tasks={dateTasks} />}
          <Escalate c={c} />
        </div>
      )}
    </div>
  )
}
