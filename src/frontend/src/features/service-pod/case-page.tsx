import { useState } from "react"
import { Link, useParams } from "react-router"
import { ArrowLeft } from "lucide-react"
import { toast } from "sonner"

import { AppPage } from "@/components/layout/app-page"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Textarea } from "@/components/ui/textarea"

import type { CaseDetail, PostingTask } from "./api"
import { Card, DemoBadge, Empty, Field, LoadError, Loading, Pill, PodTabs } from "./components/bits"
import { attempt, selectClass } from "./ui"
import { Artifacts, Messages } from "./components/case-messages"
import { Commitments, Decisions, OwnedActions, ReviewTasks } from "./components/case-sections"
import { RefreshSource } from "./components/refresh-source"
import { FLOW_UI } from "./flows"
import { useRunAction } from "./use-run-action"
import { useCase, useProposeTask } from "./hooks"
import { CASE_STATUS, formatDateTime, shortHash, TASK_STATUS, WORKFLOW_SHORT } from "./labels"

function Header({ c }: { c: CaseDetail }) {
  const [label, tone] = CASE_STATUS[c.status]
  return (
    <div className="rounded-lg border bg-card p-5">
      <Link to="/pod/cases" className="mb-2 inline-flex items-center gap-1 text-xs text-muted-foreground hover:text-foreground">
        <ArrowLeft className="size-3" aria-hidden /> All cases
      </Link>
      <p className="flex flex-wrap items-center gap-2">
        <span className="text-lg font-bold text-brand-navy">{c.reference}</span>
        <span className="text-lg">{c.title}</span>
        <Pill label={label} tone={tone} />
        {c.is_demo && <DemoBadge />}
      </p>
      <dl className="mt-3 grid gap-x-6 gap-y-1 text-xs sm:grid-cols-2 lg:grid-cols-4">
        <div>
          <dt className="text-muted-foreground">Workflow</dt>
          <dd>{WORKFLOW_SHORT[c.workflow]}</dd>
        </div>
        <div>
          <dt className="text-muted-foreground">Entity · preparer</dt>
          <dd>
            {c.entity.code} · {c.owner.name}
          </dd>
        </div>
        <div>
          <dt className="text-muted-foreground">Source</dt>
          <dd>
            {c.snapshot.company_name}, as of {c.snapshot.as_of} ({shortHash(c.snapshot.sha256)})
          </dd>
        </div>
        <div>
          <dt className="text-muted-foreground">Version · your part</dt>
          <dd>
            v{c.version} · {c.my_roles.length ? c.my_roles.join(", ").replace("_", " ") : "read only"}
          </dd>
        </div>
      </dl>
    </div>
  )
}

function CaseData({ c }: { c: CaseDetail }) {
  const { run, pending } = useRunAction(c)
  const [editing, setEditing] = useState(false)
  const [text, setText] = useState("")
  const json = JSON.stringify({ selection: c.selection, state: c.state }, null, 2)
  return (
    <Card
      title="Case data"
      hint="What the workflow selected and calculated. Workflow screens arrive in the next phases."
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

function PostingTasks({ c }: { c: CaseDetail }) {
  const propose = useProposeTask()
  const [kind, setKind] = useState<PostingTask["kind"]>("receive_payment")
  const [reference, setReference] = useState("")
  const [instructions, setInstructions] = useState('{\n  "allocations": []\n}')
  const canPropose = c.my_roles.includes("owner") && c.status === "approved"
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
              "Posting task proposed to the Finance Admin.",
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

/** One case: its source, content, people and every decision on it. */
export function CasePage() {
  const { caseId } = useParams()
  const { data: c, isPending, isError } = useCase(caseId)
  const flow = c ? FLOW_UI[c.workflow] : undefined
  return (
    <AppPage title="Service POD" subtitle={c ? `${c.reference} · updated ${formatDateTime(c.updated_at)}` : undefined}>
      <PodTabs />
      {isPending && <Loading what="the case" />}
      {isError && <LoadError what="this case (it may not exist or isn't yours)" />}
      {c && (
        <div className="space-y-6">
          <Header c={c} />
          <RefreshSource c={c} />
          <div className="grid gap-6 xl:grid-cols-[minmax(0,1fr)_380px]">
            <div className="space-y-6">
              {flow && <flow.CasePanel c={c} />}
              <ReviewTasks c={c} />
              <Messages c={c} />
              {(flow?.showsCommitments ?? true) && <Commitments c={c} />}
              <OwnedActions c={c} />
            </div>
            <div className="space-y-6">
              <Decisions c={c} />
              <Artifacts c={c} />
              {!flow?.ownsPosting && <PostingTasks c={c} />}
              <CaseData c={c} />
            </div>
          </div>
        </div>
      )}
    </AppPage>
  )
}
