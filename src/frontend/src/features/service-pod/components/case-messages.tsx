import { useState } from "react"
import { Download, Mail, Send } from "lucide-react"

import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Textarea } from "@/components/ui/textarea"
import { apiDownload } from "@/lib/api"

import type { ArtifactKind, CaseDetail, Message } from "../api"
import {
  useCreateDraft,
  useDecideArtifact,
  useEmailStatus,
  useImportReply,
  useMessageStep,
  useReconcile,
  useUpdateMessage,
  useUploadArtifact,
} from "../hooks"
import { ARTIFACT_KIND, formatDateTime, MESSAGE_STATUS } from "../labels"
import { Card, Empty, Field, Pill } from "./bits"
import { attempt, selectClass } from "../ui"

function MessageItem({ m, c }: { m: Message; c: CaseDetail }) {
  const step = useMessageStep()
  const update = useUpdateMessage()
  const reconcile = useReconcile()
  const [editing, setEditing] = useState(false)
  const [subject, setSubject] = useState(m.subject)
  const [body, setBody] = useState(m.body)
  const [note, setNote] = useState("")
  const [label, tone] = MESSAGE_STATUS[m.status]
  const owner = c.my_roles.includes("owner")
  const reviewer = c.my_roles.includes("reviewer")
  const pending = step.isPending || update.isPending || reconcile.isPending

  return (
    <li className="py-3 text-sm">
      <p className="flex flex-wrap items-center gap-2">
        <Mail className="size-4 text-muted-foreground" aria-hidden />
        <span className="font-semibold">{m.direction === "inbound" ? `From ${m.from_email}` : `To ${m.to_email}`}</span>
        <Pill label={label} tone={tone} />
        {m.simulated && <Pill label="Simulated: not sent" tone="warn" />}
        {m.thread_evidence && <span className="text-xs text-muted-foreground">thread: {m.thread_evidence}</span>}
      </p>
      {editing ? (
        <div className="mt-2 space-y-2">
          <Input value={subject} onChange={(e) => setSubject(e.target.value)} />
          <Textarea rows={6} value={body} onChange={(e) => setBody(e.target.value)} />
          <div className="flex gap-2">
            <Button
              size="sm"
              disabled={pending}
              onClick={() =>
                void attempt(
                  () => update.mutateAsync({ id: m.id, version: m.version, subject, body }),
                  "Saved: it needs approval again.",
                ).then((r) => r && setEditing(false))
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
          <p className="mt-1 font-medium">{m.subject}</p>
          <pre className="mt-1 max-h-60 overflow-auto rounded bg-secondary/40 p-2 font-sans text-xs whitespace-pre-wrap">{m.body}</pre>
        </>
      )}
      <p className="mt-1 text-xs text-muted-foreground">
        {m.direction === "inbound" ? `Received ${formatDateTime(m.received_at)}` : `Drafted by ${m.created_by}`}
        {m.approved_by && ` · approved by ${m.approved_by} (${m.provider})`}
        {m.sent_at && ` · sent ${formatDateTime(m.sent_at)}`}
        {m.artifact_ids.length > 0 && ` · ${m.artifact_ids.length} attachment(s)`}
      </p>
      {m.error && <p className="text-xs text-red-800">{m.error}</p>}
      {m.direction === "outbound" && !editing && (
        <div className="mt-2 flex flex-wrap gap-2">
          {owner && ["draft", "approved", "send_failed"].includes(m.status) && (
            <Button size="sm" variant="outline" onClick={() => setEditing(true)}>
              Edit
            </Button>
          )}
          {reviewer && m.status === "draft" && (
            <Button size="sm" disabled={pending} onClick={() => void attempt(() => step.mutateAsync({ id: m.id, version: m.version, step: "approve" }), "Message approved.")}>
              Approve message
            </Button>
          )}
          {(owner || reviewer) && m.status === "approved" && (
            <Button size="sm" disabled={pending} onClick={() => void attempt(() => step.mutateAsync({ id: m.id, version: m.version, step: "send" }), (r) => MESSAGE_STATUS[r.status][0])}>
              <Send /> Send
            </Button>
          )}
          {reviewer && m.status === "send_unknown" && (
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
    </li>
  )
}

function DraftForm({ c }: { c: CaseDetail }) {
  const create = useCreateDraft()
  const email = useEmailStatus()
  const approved = c.artifacts.filter((a) => a.status === "approved")
  const [audience, setAudience] = useState<"customer" | "internal">("customer")
  const [to, setTo] = useState("")
  const [subject, setSubject] = useState("")
  const [body, setBody] = useState("")
  const [attach, setAttach] = useState<string[]>([])
  return (
    <form
      className="mt-3 space-y-2 border-t pt-3"
      onSubmit={(e) => {
        e.preventDefault()
        void attempt(
          () =>
            create.mutateAsync({
              caseId: c.id,
              draft: { audience, purpose: "case_message", to_email: to, subject, body, artifact_ids: attach },
            }),
          "Draft saved. A reviewer approves it before it can be sent.",
        ).then((r) => {
          if (r) {
            setSubject("")
            setBody("")
            setAttach([])
          }
        })
      }}
    >
      {email.data && (
        <p className="text-xs text-muted-foreground">
          Transport: {email.data.provider}
          {email.data.simulated && " (simulated: approved messages are recorded, nothing is sent)"}
          {email.data.problem && ` · ${email.data.problem}`}
        </p>
      )}
      <div className="grid gap-2 sm:grid-cols-[140px_1fr]">
        <select className={selectClass} value={audience} onChange={(e) => setAudience(e.target.value as "customer" | "internal")} aria-label="Audience">
          <option value="customer">Customer</option>
          <option value="internal">Internal</option>
        </select>
        <Input type="email" placeholder={audience === "customer" ? "The verified contact from the source" : "A configured internal recipient"} value={to} onChange={(e) => setTo(e.target.value)} />
      </div>
      <Input placeholder="Subject" value={subject} onChange={(e) => setSubject(e.target.value)} />
      <Textarea rows={5} placeholder="Message" value={body} onChange={(e) => setBody(e.target.value)} />
      {approved.length > 0 && (
        <div className="flex flex-wrap gap-3 text-xs">
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
      <Button type="submit" size="sm" disabled={create.isPending || !to || !subject.trim() || !body.trim()}>
        Save draft
      </Button>
    </form>
  )
}

function ReplyForm({ c }: { c: CaseDetail }) {
  const importReply = useImportReply()
  const sent = c.messages.filter((m) => m.direction === "outbound" && m.status === "sent")
  const [replyTo, setReplyTo] = useState("")
  const [from, setFrom] = useState("")
  const [text, setText] = useState("")
  if (!sent.length) return null
  return (
    <div className="mt-3 space-y-2 border-t pt-3">
      <Field label="Import the customer's reply" hint="An .eml file proves the thread by its headers. Pasted text must name the message it answers.">
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
      </form>
    </div>
  )
}

export function Messages({ c }: { c: CaseDetail }) {
  const owner = c.my_roles.includes("owner")
  const canImport = owner || c.my_roles.includes("reviewer")
  const locked = ["completed", "rejected", "cancelled"].includes(c.status)
  return (
    <Card title="Messages" hint="Drafted by the preparer, approved by a reviewer, sent once. Replies only from the address it went to.">
      {c.messages.length === 0 && <Empty>No messages.</Empty>}
      <ul className="divide-y">
        {c.messages.map((m) => (
          <MessageItem key={m.id} m={m} c={c} />
        ))}
      </ul>
      {!locked && owner && <DraftForm c={c} />}
      {!locked && canImport && <ReplyForm c={c} />}
    </Card>
  )
}

export function Artifacts({ c }: { c: CaseDetail }) {
  const upload = useUploadArtifact()
  const decide = useDecideArtifact()
  const [kind, setKind] = useState<ArtifactKind>("timesheet")
  const [refs, setRefs] = useState("")
  const [file, setFile] = useState<File | null>(null)
  const owner = c.my_roles.includes("owner")
  const reviewer = c.my_roles.includes("reviewer")
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
            {reviewer && a.status === "pending" && (
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
      {owner && (
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
      )}
    </Card>
  )
}
