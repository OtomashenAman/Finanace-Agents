import { useState } from "react"
import { toast } from "sonner"

import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Textarea } from "@/components/ui/textarea"

import type { CaseDetail, PostingTask } from "../api"
import { useProposeTask } from "../hooks"
import { formatDateTime, TASK_STATUS } from "../labels"
import { attempt, selectClass } from "../ui"
import { useRunAction } from "../use-run-action"
import { Card, Empty, Field, Pill } from "./bits"

export function CaseData({ c }: { c: CaseDetail }) {
  const { run, pending } = useRunAction(c)
  const [editing, setEditing] = useState(false)
  const [text, setText] = useState("")
  const json = JSON.stringify({ selection: c.selection, state: c.state }, null, 2)
  return (
    <Card
      title="Case data"
      hint="What the workflow selected and calculated (technical view)."
      actions={
        c.allowed_actions.edit === null &&
        !editing && (
          <Button
            size="sm"
            variant="outline"
            onClick={() => {
              setText(json)
              setEditing(true)
            }}
          >
            Edit
          </Button>
        )
      }
    >
      {editing ? (
        <form
          className="space-y-2"
          onSubmit={(e) => {
            e.preventDefault()
            let parsed: { selection?: unknown; state?: unknown }
            try {
              parsed = JSON.parse(text) as typeof parsed
            } catch {
              toast.error("That isn't valid JSON.")
              return
            }
            void run("edit", { selection: parsed.selection ?? {}, state: parsed.state ?? {} }, "Saved.").then(
              (r) => r && setEditing(false),
            )
          }}
        >
          <Textarea rows={10} className="font-mono text-xs" value={text} onChange={(e) => setText(e.target.value)} />
          <div className="flex gap-2">
            <Button type="submit" size="sm" disabled={pending}>
              Save
            </Button>
            <Button type="button" size="sm" variant="outline" onClick={() => setEditing(false)}>
              Cancel
            </Button>
          </div>
        </form>
      ) : (
        <pre className="max-h-64 overflow-auto rounded bg-secondary/40 p-3 text-xs">{json}</pre>
      )}
    </Card>
  )
}

export function TaskRow({ t }: { t: PostingTask }) {
  const [label, tone] = TASK_STATUS[t.status]
  return (
    <p className="flex flex-wrap items-center gap-2">
      <span className="font-semibold">{t.reference}</span>
      <span className="text-xs text-muted-foreground">{t.kind.replace("_", " ")}</span>
      <Pill label={label} tone={tone} />
      {t.external_txn_id && <span className="text-xs">QuickBooks txn {t.external_txn_id}</span>}
    </p>
  )
}

export function PostingTasks({ c }: { c: CaseDetail }) {
  const propose = useProposeTask()
  const [kind, setKind] = useState<PostingTask["kind"]>("receive_payment")
  const [reference, setReference] = useState("")
  const [instructions, setInstructions] = useState('{\n  "allocations": []\n}')
  const canPropose = c.status === "approved"
  return (
    <Card
      title="Manual QuickBooks postings"
      hint="The application never posts. A Finance Admin posts in QuickBooks, then proves it with a fresh snapshot."
    >
      {c.posting_tasks.length === 0 && <Empty>No posting tasks.</Empty>}
      <ul className="divide-y">
        {c.posting_tasks.map((t) => (
          <li key={t.id} className="py-2 text-sm">
            <TaskRow t={t} />
            <p className="text-xs text-muted-foreground">
              Proposed by {t.proposed_by} · {formatDateTime(t.created_at)}
              {t.verified_at && ` · verified ${formatDateTime(t.verified_at)}`}
            </p>
          </li>
        ))}
      </ul>
      {canPropose && (
        <form
          className="mt-3 grid gap-2 border-t pt-3 sm:grid-cols-2"
          onSubmit={(e) => {
            e.preventDefault()
            let parsed: Record<string, unknown>
            try {
              parsed = JSON.parse(instructions) as Record<string, unknown>
            } catch {
              toast.error("Instructions must be valid JSON.")
              return
            }
            void attempt(
              () => propose.mutateAsync({ caseId: c.id, kind, reference, instructions: parsed }),
              "Posting task added: post it in QuickBooks.",
            )
          }}
        >
          <Field label="Kind">
            <select className={selectClass} value={kind} onChange={(e) => setKind(e.target.value as PostingTask["kind"])}>
              <option value="receive_payment">Receive payment</option>
              <option value="journal_entry">Journal entry</option>
            </select>
          </Field>
          <Field label="Reference" hint="e.g. the bank reference WIRE-2901">
            <Input value={reference} onChange={(e) => setReference(e.target.value)} />
          </Field>
          <Field label="What to post (JSON)">
            <Textarea rows={4} className="font-mono text-xs" value={instructions} onChange={(e) => setInstructions(e.target.value)} />
          </Field>
          <div className="flex items-end">
            <Button type="submit" size="sm" variant="outline" disabled={propose.isPending || !reference.trim()}>
              Propose posting
            </Button>
          </div>
        </form>
      )}
    </Card>
  )
}
