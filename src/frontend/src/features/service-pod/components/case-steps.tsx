import { useState, type ReactNode } from "react"
import { Link, useSearchParams } from "react-router"
import { ArrowRight, Check, ChevronDown, CircleCheck, Hourglass } from "lucide-react"

import { Button } from "@/components/ui/button"
import { cn } from "@/lib/utils"

import type { CaseDetail, WorkflowKey } from "../api"
import { useCases, useWorkflows } from "../hooks"
import { CASE_PHASE, formatDateTime, WORKFLOW_SLUG } from "../labels"
import { useRunAction } from "../use-run-action"
import type { FlowStep, NextAction } from "../flows/types"
import { CaseAudit, CaseData, PostingTasks } from "./case-extras"
import { Artifacts } from "./case-messages"
import { Pill } from "./bits"
import { OwnedActions } from "./case-sections"

function Num({ n, on }: { n: number; on: boolean }) {
  return (
    <span className={cn("flex size-5 items-center justify-center rounded-full text-xs", on ? "bg-primary text-primary-foreground" : "bg-secondary")}>
      {n}
    </span>
  )
}

const stepClass = (on: boolean) =>
  cn(
    "flex items-center gap-2 border-b-2 px-3 py-2.5 text-sm font-medium whitespace-nowrap transition-colors",
    on ? "border-primary text-primary" : "border-transparent text-muted-foreground hover:text-foreground",
  )

/** The workflow's journey on its home screen: step 1 here; each later step counts the open
 *  cases waiting on it and opens them (one case: straight onto that step). */
export function JourneyStrip({ workflow, home, steps }: { workflow: WorkflowKey; home: string; steps: Pick<FlowStep, "key" | "label">[] }) {
  const { data: cases = [] } = useCases({ workflow })
  const slug = WORKFLOW_SLUG[workflow]
  return (
    <nav aria-label="Workflow steps" className="mb-5 flex overflow-x-auto border-b">
      <span className={stepClass(true)} aria-current="step">
        <Num n={1} on />
        {home}
      </span>
      {steps.map((s, i) => {
        const waiting = cases.filter((c) => c.stage === s.key)
        const body = (
          <>
            <Num n={i + 2} on={false} />
            {s.label}
            <span className={cn("rounded-full px-1.5 text-xs", waiting.length ? "bg-amber-100 text-amber-900" : "bg-secondary")}>{waiting.length}</span>
          </>
        )
        if (waiting.length === 0)
          return (
            <span key={s.key} className={cn(stepClass(false), "cursor-default opacity-60 hover:text-muted-foreground")} title="No open case is on this step">
              {body}
            </span>
          )
        const to = waiting.length === 1 ? `/pod/cases/${waiting[0]!.id}?step=${s.key}` : `/pod/cases?workflow=${slug}&stage=${s.key}`
        return (
          <Link key={s.key} to={to} className={stepClass(false)} title={waiting.map((c) => `${c.reference} ${c.title}`).join(", ")}>
            {body}
          </Link>
        )
      })}
    </nav>
  )
}

/** Where the case stands and the one thing to do now; approving and completing happen here. */
function NextCard({ c, next, onGo }: { c: CaseDetail; next: NextAction; onGo: (step: string) => void }) {
  const { run, pending } = useRunAction(c)
  const { data: workflows } = useWorkflows()
  const signoff = workflows?.find((w) => w.key === c.workflow)?.signoff_as ?? "Finance Admin"
  const a = c.allowed_actions
  const [label, tone] = CASE_PHASE[next.phase]
  const Icon = next.kind === "done" ? CircleCheck : next.kind === "wait" ? Hourglass : ArrowRight
  const canApprove = c.status === "draft" && a.approve === null
  const canComplete = c.status === "approved" && a.complete === null
  return (
    <section aria-label="What's next" className={cn("rounded-lg border p-5", next.kind === "do" ? "border-primary/40 bg-primary/5" : "bg-card")}>
      <div className="mb-3 flex items-center justify-between gap-2">
        <h2 className="text-sm font-semibold text-brand-navy">What&apos;s next</h2>
        <Pill label={label} tone={tone} />
      </div>
      <p className="flex gap-2 text-sm">
        <Icon className={cn("mt-0.5 size-4 shrink-0", next.kind === "do" ? "text-primary" : "text-muted-foreground")} aria-hidden />
        <span>{next.text}</span>
      </p>
      <div className="mt-3 flex flex-wrap gap-2">
        {canApprove ? (
          <Button size="sm" disabled={pending} onClick={() => void run("approve", {}, signoff === "Finance Admin" ? "Case approved." : `Signed off as ${signoff}.`)}>
            {signoff === "Finance Admin" ? "Approve case" : `Sign off as ${signoff}`}
          </Button>
        ) : canComplete ? (
          <Button size="sm" disabled={pending} onClick={() => void run("complete", {}, "Case completed.")}>
            Complete case
          </Button>
        ) : (
          next.step &&
          next.kind === "do" && (
            <Button size="sm" onClick={() => onGo(next.step!)}>
              Go to it <ArrowRight />
            </Button>
          )
        )}
      </div>
      {c.status === "draft" && !canApprove && c.blockers.length > 0 && (
        <div className="mt-4 border-t pt-3 text-xs">
          <p className="mb-1 font-medium">Before it can be approved:</p>
          <ul className="list-disc space-y-0.5 pl-4 text-muted-foreground">
            {c.blockers.map((b) => (
              <li key={b}>{b}</li>
            ))}
          </ul>
        </div>
      )}
      {c.status === "approved" && !canComplete && c.completion_blockers.length > 0 && (
        <div className="mt-4 border-t pt-3 text-xs">
          <p className="mb-1 font-medium">Before it can be completed:</p>
          <ul className="list-disc space-y-0.5 pl-4 text-muted-foreground">
            {c.completion_blockers.map((b) => (
              <li key={b}>{b}</li>
            ))}
          </ul>
        </div>
      )}
      {c.approvals.length > 0 && (
        <ul className="mt-4 space-y-1 border-t pt-3 text-xs">
          {c.approvals.map((ap) => (
            <li key={ap.id} className={ap.valid ? "" : "text-muted-foreground line-through"}>
              {ap.capacity === "Finance Admin" ? "Approved" : `Signed off as ${ap.capacity}`} by {ap.user.name} · {formatDateTime(ap.created_at)}
              {!ap.valid && " (content changed since)"}
            </li>
          ))}
        </ul>
      )}
    </section>
  )
}

type StepState = "done" | "current" | "upcoming"

const STEP_DOT: Record<StepState, string> = {
  done: "bg-emerald-600 text-white",
  current: "bg-primary text-primary-foreground ring-4 ring-primary/15",
  upcoming: "border-2 border-border bg-card text-muted-foreground",
}

/** A case as one timeline: every step in order, done ones folded with a summary, the current one
 *  open. The "What's next" card beside it holds the one action (and approve / complete). */
export function CaseSteps({
  c,
  steps,
  next,
  ownsPosting,
  aside,
}: {
  c: CaseDetail
  steps: FlowStep[]
  next: NextAction
  ownsPosting: boolean
  /** More cards under "What's next" (e.g. related cases) */
  aside?: ReactNode
}) {
  // ?step= (from a worklist) opens that step; otherwise the current one is open. A click overrides.
  const [params] = useSearchParams()
  const asked = params.get("step")
  const [toggled, setToggled] = useState<Record<string, boolean>>({})
  const current = next.kind === "done" ? steps.length : Math.max(0, steps.findIndex((s) => s.key === next.step))
  const stateOf = (i: number): StepState => (i < current ? "done" : i === current ? "current" : "upcoming")
  const isOpen = (key: string, i: number) => toggled[key] ?? (asked ? key === asked : stateOf(i) === "current")
  const go = (key: string) => {
    setToggled((t) => ({ ...t, [key]: true }))
    requestAnimationFrame(() => document.getElementById(`step-${key}`)?.scrollIntoView({ behavior: "smooth", block: "start" }))
  }

  return (
    <div className="grid gap-6 xl:grid-cols-[minmax(0,1fr)_360px]">
      <ol aria-label="Case timeline" className="space-y-0">
        {steps.map((s, i) => {
          const state = stateOf(i)
          const open = isOpen(s.key, i)
          const count = s.badge?.(c) ?? 0
          const summary = state !== "upcoming" ? s.summary?.(c) : null
          return (
            <li key={s.key} id={`step-${s.key}`} className="relative scroll-mt-4 pb-6 pl-10">
              {i < steps.length - 1 && <span aria-hidden className="absolute top-8 bottom-0 left-[13px] w-px bg-border" />}
              <span
                aria-hidden
                className={cn("absolute top-1 left-0 flex size-7 items-center justify-center rounded-full text-xs font-semibold", STEP_DOT[state])}
              >
                {state === "done" ? <Check className="size-4" /> : i + 1}
              </span>
              <button
                type="button"
                aria-expanded={open}
                onClick={() => setToggled((t) => ({ ...t, [s.key]: !open }))}
                className="flex w-full items-center gap-2 py-1.5 text-left"
              >
                <span className={cn("font-semibold", state === "upcoming" ? "text-muted-foreground" : "text-brand-navy")}>{s.label}</span>
                {state === "current" && <span className="rounded bg-primary/10 px-1.5 py-0.5 text-xs font-medium text-primary">Now</span>}
                {count > 0 && <span className="rounded-full bg-amber-100 px-1.5 text-xs text-amber-900">{count}</span>}
                <ChevronDown className={cn("ml-auto size-4 text-muted-foreground transition-transform", open && "rotate-180")} aria-hidden />
              </button>
              {!open && summary && <p className="text-sm text-muted-foreground">{summary}</p>}
              {!open && state === "upcoming" && <p className="text-sm text-muted-foreground">Comes after the steps above.</p>}
              {open && (
                <div className="mt-2 space-y-6">
                  <s.Body c={c} />
                </div>
              )}
            </li>
          )
        })}
        <li className="pl-10">
          <details className="group rounded-lg border bg-card">
            <summary className="cursor-pointer px-5 py-3 text-sm font-medium text-muted-foreground hover:text-foreground">
              Documents, actions and audit details
            </summary>
            <div className="space-y-6 border-t p-5">
              <Artifacts c={c} />
              <OwnedActions c={c} />
              {!ownsPosting && <PostingTasks c={c} />}
              <CaseData c={c} />
              <CaseAudit c={c} />
            </div>
          </details>
        </li>
      </ol>
      <div className="space-y-6 xl:sticky xl:top-4 xl:self-start">
        <NextCard c={c} next={next} onGo={go} />
        {aside}
      </div>
    </div>
  )
}
