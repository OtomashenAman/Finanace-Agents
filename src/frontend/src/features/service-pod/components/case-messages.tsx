import { useState, type ComponentType, type ReactNode } from "react"
import { Download, Lock, Mail, Send, Sparkles } from "lucide-react"

import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Textarea } from "@/components/ui/textarea"
import { apiDownload } from "@/lib/api"

import type { ApprovalChecks, ArtifactKind, CaseDetail, Message } from "../api"
import {
  useCompose,
  useCreateDraft,
  useDecideArtifact,
  useEmailStatus,
  useImportReply,
  useReconcile,
  useSendMessage,
  useUpdateMessage,
  useUploadArtifact,
} from "../hooks"
import { money } from "../flows/shared"
import { ARTIFACT_KIND, formatDateTime, MESSAGE_STATUS, THREAD_EVIDENCE } from "../labels"
import { AiBadge, Card, Empty, Field, Pill } from "./bits"
import { EmailAssist } from "./email-assist"
import { attempt, selectClass } from "../ui"

const CHECK_LABELS: Record<keyof ApprovalChecks, string> = {
  recipient: "Recipient is the right contact at the customer",
  mapping: "Invoices and amounts are the right ones",
  tone: "Tone is appropriate",
}

/** What the AI read from a reply, next to the reply itself (deck: reply understanding). */
export function Extraction({ m }: { m: Message }) {
  if (!m.extraction_status) return null
  const notes = m.extraction?.notes ?? []
  const output = m.extraction?.output
  return (
    <div className="mt-2 rounded-lg border border-ai-border bg-ai-soft/70 p-2.5 text-xs">
      <p className="flex flex-wrap items-center gap-1.5 font-semibold text-ai-foreground">
        <AiBadge label="AI reading" />
        {m.extraction_status === "pending" && "in progress…"}
        {m.extraction_status === "done" && "done (checked against the customer's words)"}
        {m.extraction_status === "failed" && "couldn't be read reliably, a person reads it"}
        {m.extraction_status === "skipped" && "not available, a person reads it"}
        {m.extraction_status === "case_closed" && "not read: it came after the case was closed (open a new case if it needs action)"}
      </p>
      {m.extraction?.error && <p className="mt-1 text-red-800">{m.extraction.error}</p>}
      {notes.length > 0 && (
        <ul className="mt-1 list-disc pl-4">
          {notes.map((n) => (
            <li key={n}>{n}</li>
          ))}
        </ul>
      )}
      {output && (
        <details className="mt-1">
          <summary className="cursor-pointer text-muted-foreground">
            Structured output · {m.extraction?.provenance?.model} · {m.extraction?.provenance?.prompt_version}
          </summary>
          <pre className="mt-1 max-h-48 overflow-auto whitespace-pre-wrap">{JSON.stringify(output, null, 2)}</pre>
        </details>
      )}
    </div>
  )
}

/** The checklist, then one click: the exact message is approved and sent once. */
function SendBox({ m }: { m: Message }) {
  const send = useSendMessage()
  const [checks, setChecks] = useState<ApprovalChecks>({ recipient: false, mapping: false, tone: false })
  const customer = m.audience === "customer"
  const ready = !customer || (checks.recipient && checks.mapping && checks.tone)
  return (
    <div className="w-full space-y-1 rounded border p-2">
      {customer &&
        (Object.keys(CHECK_LABELS) as (keyof ApprovalChecks)[]).map((k) => (
          <label key={k} className="flex items-center gap-2 text-xs">
            <input type="checkbox" checked={checks[k]} onChange={(e) => setChecks({ ...checks, [k]: e.target.checked })} />
            {CHECK_LABELS[k]}
          </label>
        ))}
      <Button
        size="sm"
        disabled={send.isPending || !ready}
        onClick={() => void attempt(() => send.mutateAsync({ id: m.id, version: m.version, checks }), (r) => MESSAGE_STATUS[r.status][0])}
      >
        <Send /> Check &amp; send
      </Button>
    </div>
  )
}

type ReplyPanelType = ComponentType<{ c: CaseDetail; m: Message }>

interface CaseInvoice {
  number: string
  due_date: string
  balance: string
  days_overdue?: number
}

function initials(name: string): string {
  const words = name.replace(/@.*/, "").split(/[\s._-]+/).filter(Boolean)
  return (words.length > 1 ? words[0][0] + words[1][0] : (words[0] ?? "?").slice(0, 2)).toUpperCase()
}

/** The body, with the source's locked figures shown as their own block */
function MessageBody({ body, factBlock }: { body: string; factBlock: string | null }) {
  const at = factBlock ? body.indexOf(factBlock) : -1
  if (!factBlock || at < 0) return <p className="text-sm whitespace-pre-wrap break-words">{body}</p>
  return (
    <div className="space-y-2 text-sm">
      {body.slice(0, at).trim() && <p className="whitespace-pre-wrap break-words">{body.slice(0, at).trim()}</p>}
      <div className="rounded-lg border bg-background/80">
        <p className="flex items-center gap-1.5 border-b px-2.5 py-1 text-[11px] font-medium text-muted-foreground">
          <Lock className="size-3" aria-hidden /> Figures from the source (locked)
        </p>
        <pre className="overflow-x-auto px-2.5 py-2 font-mono text-[11px] leading-relaxed">{factBlock}</pre>
      </div>
      {body.slice(at + factBlock.length).trim() && (
        <p className="whitespace-pre-wrap break-words">{body.slice(at + factBlock.length).trim()}</p>
      )}
    </div>
  )
}

function MessageItem({ m, c, ReplyPanel }: { m: Message; c: CaseDetail; ReplyPanel?: ReplyPanelType }) {
  const update = useUpdateMessage()
  const reconcile = useReconcile()
  const [editing, setEditing] = useState(false)
  const [to, setTo] = useState(m.to_email)
  const [subject, setSubject] = useState(m.subject)
  const [body, setBody] = useState(m.body)
  const [note, setNote] = useState("")
  const sourceEmail = (c.state as { customer?: { email?: string | null } }).customer?.email ?? null
  const [label, tone] = MESSAGE_STATUS[m.status]
  const pending = update.isPending || reconcile.isPending
  const unsent = m.status === "draft" || m.status === "send_failed"
  const outbound = m.direction === "outbound"
  const who = outbound ? (m.created_by ?? "Finance team") : (m.from_email ?? "Customer")
  const when = outbound ? (m.sent_at ?? m.created_at) : (m.received_at ?? m.created_at)

  return (
    <li className={`flex gap-2.5 ${outbound ? "flex-row-reverse" : ""}`}>
      <span
        className={`mt-5 grid size-8 shrink-0 place-items-center rounded-full text-[11px] font-semibold ${outbound ? "bg-primary text-primary-foreground" : "bg-muted text-foreground"}`}
        aria-hidden
      >
        {initials(who)}
      </span>
      <div className={`flex min-w-0 flex-1 flex-col ${outbound ? "items-end" : "items-start"}`}>
        <p className={`mb-1 flex flex-wrap items-center gap-x-2 gap-y-1 text-[11px] text-muted-foreground ${outbound ? "justify-end" : ""}`}>
          <span className="font-medium text-foreground">{outbound ? `${who} → ${m.to_name ?? m.to_email}` : who}</span>
          <span>{formatDateTime(when)}</span>
          <Pill label={label} tone={tone} />
          {m.simulated && <Pill label="Simulated: not sent" tone="warn" />}
        </p>
        <div
          className={`w-full max-w-[46rem] rounded-2xl border px-3.5 py-2.5 ${
            outbound ? "rounded-tr-sm border-primary/20 bg-primary/5" : "rounded-tl-sm bg-muted/50"
          } ${unsent && outbound ? "border-dashed" : ""}`}
        >
          {editing ? (
            <div className="space-y-2">
              {m.audience === "customer" && <RecipientInput value={to} onChange={setTo} sourceEmail={sourceEmail} />}
              <Input value={subject} maxLength={300} onChange={(e) => setSubject(e.target.value)} aria-label="Subject" />
              <Textarea rows={10} className="font-mono text-xs" value={body} onChange={(e) => setBody(e.target.value)} aria-label="Message" />
              {m.fact_block && (
                <p className="flex items-center gap-1.5 text-xs text-muted-foreground">
                  <Lock className="size-3" aria-hidden /> Keep the figures block exactly as it is.
                </p>
              )}
              {m.fact_block && m.audience === "customer" && (
                <EmailAssist
                  c={c}
                  purpose={m.purpose}
                  subject={subject}
                  body={body}
                  invoiceNumbers={m.invoice_numbers}
                  onChange={(s, b) => {
                    setSubject(s)
                    setBody(b)
                  }}
                />
              )}
              <div className="flex gap-2">
                <Button
                  size="sm"
                  disabled={pending}
                  onClick={() =>
                    void attempt(() => update.mutateAsync({ id: m.id, version: m.version, subject, body, ...(to !== m.to_email ? { to_email: to } : {}) }), "Saved.").then(
                      (r) => r && setEditing(false),
                    )
                  }
                >
                  Save
                </Button>
                <Button size="sm" variant="outline" onClick={() => setEditing(false)}>
                  Cancel
                </Button>
              </div>
            </div>
          ) : (
            <>
              <p className="mb-1.5 text-sm font-semibold">{m.subject}</p>
              <div className="max-h-96 overflow-y-auto">
                <MessageBody body={m.body} factBlock={m.fact_block} />
              </div>
            </>
          )}
        </div>
        {m.invoice_numbers && (
          <p className="mt-1 text-[11px] text-muted-foreground">
            About {m.invoice_numbers.length} selected invoice(s): {m.invoice_numbers.join(", ")}
          </p>
        )}
        <p className="mt-1 text-[11px] text-muted-foreground">
          {outbound ? `Drafted by ${m.created_by}` : m.created_by ? "Imported by hand" : "Read from the mailbox"}
          {m.thread_evidence && ` · ${THREAD_EVIDENCE[m.thread_evidence] ?? m.thread_evidence}`}
          {m.approved_by && ` · checked by ${m.approved_by} (${m.provider})`}
          {m.artifact_ids.length > 0 && ` · ${m.artifact_ids.length} attachment(s)`}
        </p>
        {m.error && <p className="text-xs text-red-800">{m.error}</p>}
        {outbound && !editing && (
          <div className="mt-2 flex w-full max-w-[46rem] flex-wrap justify-end gap-2">
            {unsent && (
              <Button size="sm" variant="outline" onClick={() => setEditing(true)}>
                Edit
              </Button>
            )}
            {unsent && <SendBox m={m} />}
            {m.status === "send_unknown" && (
              <span className="flex w-full flex-wrap gap-2">
                <Input className="max-w-sm" placeholder="What the provider log shows" value={note} onChange={(e) => setNote(e.target.value)} />
                {(["sent", "send_failed"] as const).map((outcome) => (
                  <Button
                    key={outcome}
                    size="sm"
                    variant="outline"
                    disabled={pending || note.trim().length < 5}
                    onClick={() => void attempt(() => reconcile.mutateAsync({ id: m.id, version: m.version, outcome, note }), "Reconciled.")}
                  >
                    It was {outcome === "sent" ? "sent" : "not sent"}
                  </Button>
                ))}
              </span>
            )}
          </div>
        )}
        {!outbound && <div className="mt-2 w-full">{ReplyPanel ? <ReplyPanel c={c} m={m} /> : <Extraction m={m} />}</div>}
      </div>
    </li>
  )
}

/** The customer's address: QuickBooks' contact by default, any other address allowed */
function RecipientInput({ value, onChange, sourceEmail }: { value: string; onChange: (v: string) => void; sourceEmail: string | null }) {
  const other = Boolean(sourceEmail && value.trim() && value.trim().toLowerCase() !== sourceEmail.toLowerCase())
  return (
    <div className="space-y-1">
      <Input type="email" placeholder="To: any address at the customer" value={value} onChange={(e) => onChange(e.target.value)} aria-label="To" />
      {other && (
        <p className="text-[11px] text-amber-800">
          Not the QuickBooks contact ({sourceEmail}).{" "}
          <button type="button" className="underline" onClick={() => onChange(sourceEmail ?? "")}>
            Use it instead
          </button>
        </p>
      )}
      {!value.trim() && sourceEmail && (
        <button type="button" className="text-[11px] text-primary hover:underline" onClick={() => onChange(sourceEmail)}>
          Use the QuickBooks contact: {sourceEmail}
        </button>
      )}
    </div>
  )
}

/** Which of the case's invoices the email is about; all are selected to start with */
function InvoicePicker({
  rows,
  currency,
  picked,
  onChange,
}: {
  rows: CaseInvoice[]
  currency: unknown
  picked: string[]
  onChange: (numbers: string[]) => void
}) {
  const all = picked.length === rows.length
  const total = rows.filter((r) => picked.includes(r.number)).reduce((sum, r) => sum + Number(r.balance), 0)
  return (
    <fieldset className="overflow-hidden rounded-lg border">
      <legend className="sr-only">Invoices in this email</legend>
      <div className="flex flex-wrap items-center justify-between gap-2 border-b bg-muted/40 px-3 py-2 text-xs">
        <label className="flex cursor-pointer items-center gap-2 font-medium">
          <input
            type="checkbox"
            checked={all}
            ref={(el) => {
              if (el) el.indeterminate = !all && picked.length > 0
            }}
            onChange={(e) => onChange(e.target.checked ? rows.map((r) => r.number) : [])}
          />
          Select all ({rows.length})
        </label>
        <span className="text-muted-foreground">
          {picked.length} selected · <span className="font-medium text-foreground tabular-nums">{money(total, currency)}</span>
        </span>
      </div>
      <ul className="max-h-56 divide-y overflow-y-auto">
        {rows.map((r) => (
          <li key={r.number}>
            <label className="flex cursor-pointer items-center gap-3 px-3 py-1.5 text-xs hover:bg-muted/30">
              <input
                type="checkbox"
                checked={picked.includes(r.number)}
                onChange={(e) => onChange(e.target.checked ? rows.map((x) => x.number).filter((n) => n === r.number || picked.includes(n)) : picked.filter((n) => n !== r.number))}
              />
              <span className="w-28 shrink-0 font-medium">{r.number}</span>
              <span className="text-muted-foreground">
                due {r.due_date}
                {r.days_overdue ? ` · ${r.days_overdue} days overdue` : ""}
              </span>
              <span className="ml-auto tabular-nums">{money(r.balance, currency)}</span>
            </label>
          </li>
        ))}
      </ul>
      {picked.length === 0 && <p className="border-t px-3 py-2 text-xs text-amber-800">Select at least one invoice for the email.</p>}
    </fieldset>
  )
}

function Step({ n, title, children }: { n: number; title: string; children: ReactNode }) {
  return (
    <section className="space-y-2">
      <h4 className="flex items-center gap-2 text-xs font-semibold">
        <span className="grid size-5 place-items-center rounded-full bg-primary/10 text-[11px] text-primary">{n}</span>
        {title}
      </h4>
      {children}
    </section>
  )
}

function DraftForm({
  c,
  purposes,
  defaultPurpose,
}: {
  c: CaseDetail
  purposes: Record<string, string>
  defaultPurpose?: string
}) {
  const create = useCreateDraft()
  const compose = useCompose()
  const email = useEmailStatus()
  const approved = c.artifacts.filter((a) => a.status === "approved")
  const state = c.state as { invoices?: CaseInvoice[]; currency?: string; customer?: { email?: string | null } }
  const caseInvoices = state.invoices ?? []
  const [purpose, setPurpose] = useState(defaultPurpose ?? Object.keys(purposes)[0] ?? "case_message")
  const [audience, setAudience] = useState<"customer" | "internal">("customer")
  const [to, setTo] = useState("")
  const [subject, setSubject] = useState("")
  const [body, setBody] = useState("")
  const [attach, setAttach] = useState<string[]>([])
  const [picked, setPicked] = useState<string[]>(() => caseInvoices.map((r) => r.number))
  // The selection the current draft's figures were written for (null: typed by hand)
  const [draftFor, setDraftFor] = useState<string | null>(null)
  const [composedNote, setComposedNote] = useState<string | null>(null)
  const workflowPurpose = purpose !== "case_message"
  const picking = workflowPurpose && caseInvoices.length > 0
  const only = picking && picked.length < caseInvoices.length ? picked : null
  const selectionKey = (only ?? ["*"]).join("|")
  const stale = picking && body.trim() !== "" && draftFor !== null && draftFor !== selectionKey
  const nothingPicked = picking && picked.length === 0

  const write = () =>
    void attempt(() => compose.mutateAsync({ caseId: c.id, purpose, invoice_numbers: only }), (d) =>
      d.ai_drafted
        ? "Draft suggested (AI wording, figures from the source)."
        : d.note?.includes("saved email template")
          ? "Draft from the customer's saved template (figures from the source)."
          : "Template draft (no AI wording).",
    ).then((d) => {
      if (!d) return
      setTo(d.to_email ?? "")
      setSubject(d.subject)
      setBody(d.body)
      setComposedNote(d.note)
      setDraftFor(selectionKey)
    })

  return (
    <form
      className="mt-4 space-y-4 rounded-xl border bg-card p-3 shadow-2xs"
      onSubmit={(e) => {
        e.preventDefault()
        void attempt(
          () =>
            create.mutateAsync({
              caseId: c.id,
              draft: { audience, purpose, to_email: to, subject, body, artifact_ids: attach, invoice_numbers: workflowPurpose ? only : null },
            }),
          "Draft saved: check it and send it when ready.",
        ).then((r) => {
          if (r) {
            setSubject("")
            setBody("")
            setAttach([])
            setComposedNote(null)
            setDraftFor(null)
          }
        })
      }}
    >
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h3 className="flex items-center gap-2 text-sm font-semibold">
          <Mail className="size-4 text-muted-foreground" aria-hidden /> New email
        </h3>
        <select
          className={`${selectClass} w-auto`}
          value={purpose}
          onChange={(e) => {
            setPurpose(e.target.value)
            if (e.target.value !== "case_message") setAudience("customer")
          }}
          aria-label="Purpose"
        >
          {Object.entries(purposes).map(([k, v]) => (
            <option key={k} value={k}>
              {v}
            </option>
          ))}
          <option value="case_message">Other message (no figures)</option>
        </select>
      </div>
      {email.data && (
        <p className="text-xs text-muted-foreground">
          Sends via {email.data.provider}
          {email.data.sender && ` from ${email.data.sender}`}
          {email.data.simulated && " (simulated: approved messages are recorded, nothing is sent)"}
          {email.data.problem && ` · ${email.data.problem}`}
        </p>
      )}
      {email.data?.test_recipient && !email.data.simulated && (
        <p className="rounded-md bg-amber-50 px-3 py-2 text-xs text-amber-900">
          Test mode: every email goes to <strong>{email.data.test_recipient}</strong>, not the customer (the subject names the real recipient).
        </p>
      )}

      {picking && (
        <Step n={1} title="Pick the invoices for this email">
          <InvoicePicker rows={caseInvoices} currency={state.currency} picked={picked} onChange={setPicked} />
        </Step>
      )}

      <Step n={picking ? 2 : 1} title="Write the email">
        {workflowPurpose && (
          <div className="flex flex-wrap items-center gap-2">
            <Button type="button" size="sm" disabled={compose.isPending || nothingPicked} onClick={write}>
              <Sparkles /> {compose.isPending ? "Writing…" : body.trim() ? "Write it again" : "Write draft"}
            </Button>
            <span className="text-xs text-muted-foreground">
              {picking ? `For ${only ? `${picked.length} of ${caseInvoices.length}` : `all ${caseInvoices.length}`} invoice(s).` : "Figures come from the source."}
            </span>
          </div>
        )}
        {stale && (
          <p className="flex flex-wrap items-center gap-2 rounded-md bg-amber-50 px-3 py-2 text-xs text-amber-900">
            The invoice selection changed: write the draft again so its figures match.
            <Button type="button" size="sm" variant="outline" className="h-7 px-2 text-xs" disabled={compose.isPending || nothingPicked} onClick={write}>
              Update draft
            </Button>
          </p>
        )}
        {composedNote &&
          (composedNote.startsWith("Draft suggested") ? (
            <p className="flex flex-wrap items-center gap-1.5 text-xs text-ai-foreground">
              <AiBadge label="AI wording" />
              {composedNote}
            </p>
          ) : (
            <p className={`text-xs ${composedNote.includes("saved email template") ? "text-muted-foreground" : "text-amber-800"}`}>{composedNote}</p>
          ))}
        <div className="space-y-2 rounded-lg border bg-background p-2.5">
          <div className="grid gap-2 sm:grid-cols-[120px_1fr]">
            <select
              className={selectClass}
              value={audience}
              disabled={workflowPurpose}
              onChange={(e) => setAudience(e.target.value as "customer" | "internal")}
              aria-label="Audience"
            >
              <option value="customer">Customer</option>
              <option value="internal">Internal</option>
            </select>
            {audience === "customer" ? (
              <RecipientInput value={to} onChange={setTo} sourceEmail={state.customer?.email ?? null} />
            ) : (
              <Input type="email" placeholder="To: a configured internal recipient" value={to} onChange={(e) => setTo(e.target.value)} aria-label="To" />
            )}
          </div>
          <Input placeholder="Subject" maxLength={300} value={subject} onChange={(e) => setSubject(e.target.value)} aria-label="Subject" />
          <Textarea
            rows={10}
            className="font-mono text-xs"
            placeholder={workflowPurpose ? "Click Write draft, or ask the AI below." : "Message"}
            value={body}
            onChange={(e) => setBody(e.target.value)}
            aria-label="Message"
          />
          {workflowPurpose && body.trim() && (
            <p className="flex items-center gap-1.5 text-xs text-muted-foreground">
              <Lock className="size-3" aria-hidden /> Edit the wording freely; keep the invoice table exactly as it is.
            </p>
          )}
        </div>
        {workflowPurpose && audience === "customer" && (
          <EmailAssist
            c={c}
            purpose={purpose}
            subject={subject}
            body={body}
            invoiceNumbers={only}
            onChange={(s, b) => {
              setSubject(s)
              setBody(b)
              setComposedNote(null)
              setDraftFor(selectionKey)
              if (!to) setTo(state.customer?.email ?? "")
            }}
          />
        )}
      </Step>

      <Step n={picking ? 3 : 2} title="Save it, then check and send">
        {approved.length > 0 && (
          <div className="flex flex-wrap gap-3 text-xs">
            <span className="text-muted-foreground">Attach:</span>
            {approved.map((a) => (
              <label key={a.id} className="flex items-center gap-1">
                <input
                  type="checkbox"
                  checked={attach.includes(a.id)}
                  onChange={(e) => setAttach(e.target.checked ? [...attach, a.id] : attach.filter((x) => x !== a.id))}
                />
                {a.filename}
              </label>
            ))}
          </div>
        )}
        <Button type="submit" size="sm" disabled={create.isPending || stale || nothingPicked || !to || !subject.trim() || !body.trim()}>
          Save draft
        </Button>
      </Step>
    </form>
  )
}

function ReplyForm({ c }: { c: CaseDetail }) {
  const importReply = useImportReply()
  const sent = c.messages.filter((m) => m.direction === "outbound" && m.status === "sent")
  const [replyTo, setReplyTo] = useState("")
  const [from, setFrom] = useState("")
  const [text, setText] = useState("")
  const [open, setOpen] = useState(false)
  if (!sent.length) return null
  if (!open)
    return (
      <p className="mt-3 border-t pt-3 text-xs text-muted-foreground">
        Replies to our email are picked up from the mailbox automatically.{" "}
        <button type="button" className="text-primary hover:underline" onClick={() => setOpen(true)}>
          Import a reply by hand
        </button>{" "}
        if it came another way.
      </p>
    )
  return (
    <div className="mt-3 space-y-2 border-t pt-3">
      <Field label="Import a reply by hand" hint="An .eml file proves the thread by its headers. Pasted text must name the message it answers.">
        <Input
          type="file"
          accept=".eml,message/rfc822"
          onChange={(e) => {
            const file = e.target.files?.[0]
            if (file)
              void file.text().then((raw_eml) => attempt(() => importReply.mutateAsync({ caseId: c.id, raw_eml }), "Reply imported."))
            e.target.value = ""
          }}
        />
      </Field>
      <form
        className="grid gap-2 sm:grid-cols-2"
        onSubmit={(e) => {
          e.preventDefault()
          void attempt(
            () => importReply.mutateAsync({ caseId: c.id, from_email: from, body: text, reply_to_message_id: replyTo }),
            "Reply imported.",
          )
        }}
      >
        <select className={selectClass} value={replyTo} onChange={(e) => setReplyTo(e.target.value)} aria-label="Answers">
          <option value="">Answers which message…</option>
          {sent.map((m) => (
            <option key={m.id} value={m.id}>
              {m.subject}
            </option>
          ))}
        </select>
        <Input type="email" placeholder="Sender" value={from} onChange={(e) => setFrom(e.target.value)} />
        <Textarea className="sm:col-span-2" rows={3} placeholder="Pasted reply text" value={text} onChange={(e) => setText(e.target.value)} />
        <Button type="submit" size="sm" variant="outline" disabled={importReply.isPending || !replyTo || !from || !text.trim()}>
          Import pasted reply
        </Button>
        <Button type="button" size="sm" variant="ghost" onClick={() => setOpen(false)}>
          Cancel
        </Button>
      </form>
    </div>
  )
}

interface MessagesProps {
  c: CaseDetail
  title?: string
  hint?: ReactNode
  /** Which messages this view shows (default: all) */
  filter?: (m: Message) => boolean
  /** Show the draft composer */
  compose?: boolean
  /** Show the reply import */
  importReplies?: boolean
  /** The workflow's message purposes (purpose -> label) */
  purposes?: Record<string, string>
  defaultPurpose?: string
  /** How a reply is reviewed next to the raw email (default: the AI reading box) */
  ReplyPanel?: ReplyPanelType
  empty?: string
}

export function Messages({
  c,
  title = "Messages",
  hint = "Drafted, checked and approved, then sent once. Replies only from the address it went to.",
  filter = () => true,
  compose = true,
  importReplies = true,
  purposes = {},
  defaultPurpose,
  ReplyPanel,
  empty = "No messages.",
}: MessagesProps) {
  const locked = ["completed", "cancelled"].includes(c.status)
  const shown = c.messages.filter(filter)
  return (
    <Card title={title} hint={hint}>
      {shown.length === 0 && <Empty>{empty}</Empty>}
      <ul className="space-y-5">
        {shown.map((m) => (
          <MessageItem key={m.id} m={m} c={c} ReplyPanel={ReplyPanel} />
        ))}
      </ul>
      {!locked && compose && <DraftForm c={c} purposes={purposes} defaultPurpose={defaultPurpose} />}
      {!locked && importReplies && <ReplyForm c={c} />}
    </Card>
  )
}

export function Artifacts({ c }: { c: CaseDetail }) {
  const upload = useUploadArtifact()
  const decide = useDecideArtifact()
  const [kind, setKind] = useState<ArtifactKind>("timesheet")
  const [refs, setRefs] = useState("")
  const [file, setFile] = useState<File | null>(null)
  return (
    <Card title="Supporting documents" hint="Tied to invoices of this case; attachable only once approved.">
      {c.artifacts.length === 0 && <Empty>No documents.</Empty>}
      <ul className="divide-y">
        {c.artifacts.map((a) => (
          <li key={a.id} className="flex flex-wrap items-center gap-2 py-2 text-sm">
            <span className="font-medium">{a.filename}</span>
            <span className="text-xs text-muted-foreground">
              {ARTIFACT_KIND[a.kind]} · {a.invoice_refs.join(", ") || "no invoice"} · by {a.uploaded_by}
            </span>
            <Pill label={a.status} tone={a.status === "approved" ? "good" : a.status === "rejected" ? "bad" : "neutral"} />
            <Button size="sm" variant="ghost" onClick={() => void apiDownload(`/pod/artifacts/${a.id}/content`, a.filename)} aria-label={`Download ${a.filename}`}>
              <Download />
            </Button>
            {a.status === "pending" && (
              <>
                <Button size="sm" disabled={decide.isPending} onClick={() => void attempt(() => decide.mutateAsync({ id: a.id, decision: "approved" }), "Document approved.")}>
                  Approve
                </Button>
                <Button size="sm" variant="outline" disabled={decide.isPending} onClick={() => void attempt(() => decide.mutateAsync({ id: a.id, decision: "rejected" }), "Document rejected.")}>
                  Reject
                </Button>
              </>
            )}
          </li>
        ))}
      </ul>
      <form
        className="mt-3 grid gap-2 border-t pt-3 sm:grid-cols-[150px_1fr_1fr_auto]"
        onSubmit={(e) => {
          e.preventDefault()
          if (file) void attempt(() => upload.mutateAsync({ caseId: c.id, file, kind, invoiceRefs: refs }), "Document added.")
        }}
      >
        <select className={selectClass} value={kind} onChange={(e) => setKind(e.target.value as ArtifactKind)} aria-label="Kind">
          {Object.entries(ARTIFACT_KIND).map(([k, v]) => (
            <option key={k} value={k}>
              {v}
            </option>
          ))}
        </select>
        <Input placeholder="Invoices, e.g. INV-101, INV-102" value={refs} onChange={(e) => setRefs(e.target.value)} />
        <Input type="file" onChange={(e) => setFile(e.target.files?.[0] ?? null)} />
        <Button type="submit" size="sm" variant="outline" disabled={!file || upload.isPending}>
          Upload
        </Button>
      </form>
    </Card>
  )
}
