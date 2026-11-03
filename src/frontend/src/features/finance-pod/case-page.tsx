import { useState } from "react"
import { useParams } from "react-router"
import { Bot, ChevronDown, ChevronRight, CircleAlert, CircleCheck, CircleX, Clock, User } from "lucide-react"
import { toast } from "sonner"

import { Button } from "@/components/ui/button"
import { Card, GuardedButton, LoadError, Loading } from "@/features/service-pod/components/bits"
import { errorMessage } from "@/lib/api"
import { cn } from "@/lib/utils"

import { useCaseAction, useFinanceCase, useFinanceWorkflows } from "./hooks"
import { CASE_STATUS, capacityLabel, KIND_META } from "./labels"
import { FinancePage } from "./components/finance-page"
import { ActionsPanel, DocumentsPanel, MessagesPanel, PostingsPanel } from "./components/case-panels"
import { StepCard } from "./components/step-card"
import { TestAs } from "./components/test-as"
import { namesOf, ResultNames } from "./components/result-names"
import type { CaseDetail } from "./api"

const DOT: Record<string, string> = {
  done: "bg-emerald-500",
  not_applicable: "bg-slate-300",
  failed: "bg-red-500",
  pending: "bg-muted-foreground/25",
}

/** Where the case is: one dot per step (done, not applicable, failed, to do), how many are
 *  settled, and what's next. */
function Progress({ c, current }: { c: CaseDetail; current: string | undefined }) {
  const settled = c.steps.filter((s) => s.status === "done" || s.status === "not_applicable").length
  const step = c.steps.find((s) => s.key === current)
  const failed = step?.status === "failed"
  return (
    <div className="mb-4">
      <div className="flex flex-wrap items-baseline justify-between gap-2 text-sm">
        <span className="font-medium">
          {settled} of {c.steps.length} steps done
        </span>
        <span className={cn("text-xs", failed ? "font-medium text-red-700" : "text-muted-foreground")}>
          {c.status === "completed" ? "Completed" : c.status === "cancelled" ? "Cancelled" : step ? `${failed ? "Failed: " : "Next: "}${step.title}` : "Every step is settled"}
        </span>
      </div>
      <ol className="mt-2 flex gap-1" aria-label="Steps">
        {c.steps.map((s) => (
          <li key={s.key} className="min-w-0 flex-1">
            <a href={`#step-${s.key}`} title={`${s.key} ${s.title}: ${s.status.replace("_", " ")}`}
              className={cn("block h-2 rounded-full", DOT[s.status], s.key === current && "ring-2 ring-primary ring-offset-1")} />
          </li>
        ))}
      </ol>
    </div>
  )
}

function Legend() {
  return (
    <ul className="flex flex-wrap gap-3 text-xs text-muted-foreground" aria-label="Step colours">
      {(["agent", "person", "system"] as const).map((kind) => (
        <li key={kind} className="flex items-center gap-1.5">
          <span className={cn("inline-block size-3 rounded-sm", KIND_META[kind].chip)} />
          {KIND_META[kind].label}
        </li>
      ))}
    </ul>
  )
}


const SETTLED = new Set(["done", "not_applicable"])

/** The one thing to know about the case now, and the button for it: what failed and why,
 *  what an agent needs before it runs (and where to fix it), whose turn it is, or that it's
 *  finished. Other blockers (review tasks, rules) are listed under it. */
function WhatsNext({ c, onRun, onFix, onApprove, busy }: {
  c: CaseDetail
  onRun: (key: string) => void
  onFix: (key: string, why: string) => void
  onApprove: () => void
  busy: boolean
}) {
  const step = c.steps.find((s) => !SETTLED.has(s.status))
  const extra = c.blockers.filter((b) => !/step\(s\) (not done yet|must be redone)/.test(b))
  let tone = "border-sky-200 bg-sky-50 text-sky-950"
  let icon = <Clock className="size-5 text-sky-700" aria-hidden />
  let title: string
  let body: string | null = null
  let button: React.ReactNode = null
  let testAs: React.ReactNode = null
  if (c.status === "completed" || c.status === "cancelled") {
    tone = "border-slate-200 bg-slate-50 text-slate-800"
    icon = <CircleCheck className="size-5 text-slate-600" aria-hidden />
    title = c.status === "completed" ? "This case is completed." : "This case was cancelled."
  } else if (step?.needs) {
    tone = "border-amber-300 bg-amber-50 text-amber-950"
    icon = <CircleAlert className="size-5 text-amber-700" aria-hidden />
    title = `"${step.title}" won't run until something is fixed`
    body = step.needs.fix_title ? `In "${step.needs.fix_title}": ${step.needs.message}` : step.needs.message
    if (step.needs.fix_step) {
      button = (
        <Button size="sm" disabled={busy} onClick={() => onFix(step.needs!.fix_step!, step.needs!.message)}>
          Go back to "{step.needs.fix_title}" and fix it
        </Button>
      )
    }
  } else if (step?.status === "failed") {
    tone = "border-red-200 bg-red-50 text-red-950"
    icon = <CircleX className="size-5 text-red-600" aria-hidden />
    title = `${step.kind === "agent" ? "The agent couldn't finish" : "Failed"}: ${step.title}`
    body = step.l5.find((l) => l.note)?.note ?? null
    if (step.blocked === null && step.kind === "agent") {
      button = <Button size="sm" disabled={busy} onClick={() => onRun(step.key)}><Bot className="size-4" aria-hidden /> Run again</Button>
    }
  } else if (step) {
    const who = step.kind === "agent" ? "the agent" : step.capacity ? capacityLabel(step.capacity) : "a person"
    const back = step.l5.find((l) => l.note?.startsWith("Sent back: "))?.note?.replace(/^Sent back: (To fix: )?/, "")
    if (back) tone = "border-amber-300 bg-amber-50 text-amber-950"
    title = back ? `Sent back to fix: ${step.title}` : `Next: ${step.title}`
    body = back
      ? `${back.charAt(0).toUpperCase()}${back.slice(1)}${step.blocked === null ? " Change it in the form below, then submit." : ` Waiting on ${who}.`}`
      : step.blocked === null
        ? step.kind === "agent" ? "You can start the agent now." : "It's yours: fill it in below."
        : `Waiting on ${who}.`
    if (step.blocked === null && step.kind === "agent") {
      button = <Button size="sm" disabled={busy} onClick={() => onRun(step.key)}><Bot className="size-4" aria-hidden /> Run the agent</Button>
    } else if (step.blocked === null) {
      button = <a href={`#step-${step.key}`} className="text-sm font-medium text-primary hover:underline">Go to the form ↓</a>
    }
    if (step.kind !== "agent" && step.capacity && !/ waits on /.test(step.blocked ?? "")) {
      testAs = <TestAs caseId={c.id} step={step.key} capacity={step.capacity} />
    }
  } else if (c.status === "draft" && c.next_signoff) {
    title = `Every step is done: sign off as ${capacityLabel(c.next_signoff)}`
    button = <GuardedButton reason={c.allowed_actions.approve} onClick={onApprove} disabled={busy}>Sign off as {capacityLabel(c.next_signoff)}</GuardedButton>
    testAs = <TestAs caseId={c.id} capacity={c.next_signoff} />
  } else if (c.status === "approved") {
    tone = "border-emerald-200 bg-emerald-50 text-emerald-950"
    icon = <CircleCheck className="size-5 text-emerald-700" aria-hidden />
    title = c.allowed_actions.complete === null ? "Released: ready to complete" : "Released"
    body = c.blockers[0] ?? null
  } else {
    title = "Every step is settled."
  }
  return (
    <section aria-label="What's next" className={cn("mb-4 rounded-xl border p-4", tone)}>
      <div className="flex gap-3">
        <span className="mt-0.5 shrink-0">{icon}</span>
        <div className="min-w-0 flex-1 space-y-1">
          <p className="font-semibold">{title}</p>
          {body && <p className="text-sm">{body}</p>}
          {extra.length > 0 && (
            <ul className="mt-1 space-y-0.5 text-sm">
              {extra.map((b) => <li key={b} className="flex gap-1.5"><CircleAlert className="mt-0.5 size-3.5 shrink-0" aria-hidden />{b}</li>)}
            </ul>
          )}
          {button && <div className="pt-1">{button}</div>}
          {testAs}
        </div>
      </div>
    </section>
  )
}

/** The steps after the one(s) being worked on, as one quiet line each. */
function ComingNext({ steps }: { steps: CaseDetail["steps"] }) {
  const [open, setOpen] = useState(false)
  if (steps.length === 0) return null
  return (
    <div className="rounded-xl border border-dashed border-border p-3">
      <button type="button" onClick={() => setOpen((v) => !v)} className="flex w-full items-center gap-2 text-left text-sm font-medium">
        {open ? <ChevronDown className="size-4" aria-hidden /> : <ChevronRight className="size-4" aria-hidden />}
        <span className="shrink-0 whitespace-nowrap">Coming next ({steps.length})</span>
        {!open && <span className="min-w-0 truncate font-normal text-muted-foreground">{steps.map((s) => s.title).join(" → ")}</span>}
      </button>
      {open && (
        <ol className="mt-2 space-y-1.5 pl-6 text-sm">
          {steps.map((s) => (
            <li key={s.key} id={`step-${s.key}`} className="flex items-center gap-2">
              {s.kind === "agent" ? <Bot className="size-3.5 text-sky-600" aria-hidden /> : <User className="size-3.5 text-amber-600" aria-hidden />}
              <span>{s.title}</span>
              <span className="text-xs text-muted-foreground">{s.kind === "agent" ? "agent" : s.capacity ? capacityLabel(s.capacity) : ""}</span>
            </li>
          ))}
        </ol>
      )}
    </div>
  )
}

export function FinanceCasePage() {
  const { caseId } = useParams()
  const { data: c, isLoading, isError } = useFinanceCase(caseId)
  const workflows = useFinanceWorkflows()
  const action = useCaseAction()
  const [expandAll, setExpandAll] = useState(false)

  if (isLoading) return <FinancePage title="Case"><Loading what="the case" /></FinancePage>
  if (isError || !c) return <FinancePage title="Case"><LoadError what="the case" /></FinancePage>

  const workflow = workflows.data?.find((w) => w.key === c.workflow)
  const current = c.steps.find((s) => s.status === "pending" || s.status === "failed")?.key
  const act = (name: string, payload: Record<string, unknown>, done: string, then?: () => void) =>
    action.mutate(
      { id: c.id, version: c.version, action: name, payload },
      {
        onSuccess: () => { toast.success(done); then?.() },
        onError: (error) => toast.error(errorMessage(error, "That didn't work.")),
      },
    )
  const approve = () => act("approve", {}, c.next_signoff ? `Signed off as ${capacityLabel(c.next_signoff)}` : "Approved")
  const run = (key: string) => act("run_agent_step", { step: key }, `Step ${key} ran`)
  const fix = (key: string, why: string) =>
    act("redo_step", { step: key, reason: `To fix: ${why}` }, `Step ${key} is open again: fix it there`, () =>
      setTimeout(() => document.getElementById(`step-${key}`)?.scrollIntoView({ behavior: "smooth", block: "start" }), 400),
    )

  // Done steps fold; the step(s) being worked on are open; the rest wait in one quiet list
  const settledSteps = c.steps.filter((s) => SETTLED.has(s.status))
  const active = c.steps.filter((s) => !SETTLED.has(s.status) && (s.key === current || s.status === "failed" || s.blocked === null || s.needs))
  const later = c.steps.filter((s) => !SETTLED.has(s.status) && !active.includes(s))
  const shownSteps = expandAll ? c.steps : [...settledSteps, ...active]
  const signoffs = (workflow?.signoffs.length ?? 0) > 0

  return (
    <FinancePage title={`${c.reference} · ${c.title}`} subtitle={`${workflow?.name ?? c.workflow} · ${c.entity.code} · opened by ${c.owner.name}`}>
      <div className="grid grid-cols-[minmax(0,1fr)] gap-4 lg:grid-cols-[minmax(0,1fr)_320px]">
        <div className="min-w-0">
          <WhatsNext c={c} onRun={run} onFix={fix} onApprove={approve} busy={action.isPending} />
          <Card
            title="Steps"
            hint="The requirement's L4 tasks in order. Finished steps fold to one line."
            actions={
              <div className="flex flex-wrap items-center gap-3">
                <Legend />
                <button type="button" className="text-xs font-medium text-primary hover:underline" onClick={() => setExpandAll((v) => !v)}>
                  {expandAll ? "Fold" : "Show every step"}
                </button>
              </div>
            }
          >
            <Progress c={c} current={current} />
            <ResultNames.Provider value={namesOf(c)}>
              <div className="space-y-3">
                {shownSteps.map((step) => (
                  <div key={step.key} id={`step-${step.key}`} className="scroll-mt-4">
                    <StepCard c={c} step={step} open={step.key === current} expandAll={expandAll} />
                  </div>
                ))}
                {!expandAll && <ComingNext steps={later} />}
              </div>
            </ResultNames.Provider>
          </Card>
        </div>

        <div className="space-y-4">
          <Card title="Case">
            <span className={cn("rounded-full px-2 py-0.5 text-xs font-medium", CASE_STATUS[c.status].className)}>
              {c.status === "approved" ? "Released" : CASE_STATUS[c.status].label}
            </span>
            <dl className="mt-3 space-y-1 text-xs">
              <div className="flex justify-between gap-2"><dt className="text-muted-foreground">Opened by</dt><dd>{c.owner.name}</dd></div>
              <div className="flex justify-between gap-2"><dt className="text-muted-foreground">Entity</dt><dd>{c.entity.code}</dd></div>
              {c.approvals.filter((a) => a.valid).map((a) => (
                <div key={a.id} className="flex justify-between gap-2">
                  <dt className="text-muted-foreground">{a.capacity === "released" ? "Released" : `Signed off (${capacityLabel(a.capacity)})`}</dt>
                  <dd>{a.capacity === "released" ? new Date(a.created_at).toLocaleDateString() : a.user.name}</dd>
                </div>
              ))}
            </dl>
            {signoffs && (
              <p className="mt-2 text-xs text-muted-foreground">
                Needs sign-off: {workflow!.signoffs.map((s) => capacityLabel(s)).join(", then ")}
              </p>
            )}
          </Card>

          <ActionsPanel c={c} />
          <MessagesPanel c={c} />
          <PostingsPanel c={c} />
          <DocumentsPanel c={c} />

          {c.review_tasks.length > 0 && (
            <Card title="Review tasks">
              <ul className="space-y-2 text-sm">
                {c.review_tasks.map((t) => (
                  <li key={t.id}>
                    <span className="font-medium">{t.subject ?? t.kind.replace(/_/g, " ")}</span>
                    <p className="text-xs text-muted-foreground">{t.detail}</p>
                    {t.status === "resolved" && <p className="text-xs">Resolved: {t.resolution}</p>}
                  </li>
                ))}
              </ul>
            </Card>
          )}
        </div>
      </div>
    </FinancePage>
  )
}
