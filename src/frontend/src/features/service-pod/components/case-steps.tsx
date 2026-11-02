import { useState, type ReactNode } from "react"
import { Link, useSearchParams } from "react-router"
import { ArrowRight, Check, CircleCheck, Hourglass } from "lucide-react"

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
    <section aria-label="What's next" className={cn("rounded-lg border p-4 shadow-2xs transition-shadow", next.kind === "do" ? "border-primary/50 bg-primary/5 dark:bg-primary/10" : "border-border/70 bg-card")}>
      <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-3">
        <div className="space-y-1">
          <div className="flex items-center gap-2">
            <span className="text-[11px] font-bold uppercase tracking-wider text-muted-foreground">What&apos;s next</span>
            <Pill label={label} tone={tone} />
          </div>
          <p className="flex items-start gap-2 text-sm">
            <Icon className={cn("mt-0.5 size-4 shrink-0", next.kind === "do" ? "text-primary" : "text-muted-foreground")} aria-hidden />
            <span className="font-medium text-foreground">{next.text}</span>
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-2 shrink-0">
          {canApprove ? (
            <Button size="sm" className="shadow-xs font-semibold px-4" disabled={pending} onClick={() => void run("approve", {}, signoff === "Finance Admin" ? "Case approved." : `Signed off as ${signoff}.`)}>
              {signoff === "Finance Admin" ? "Approve case" : `Sign off as ${signoff}`}
            </Button>
          ) : canComplete ? (
            <Button size="sm" className="shadow-xs font-semibold px-4" disabled={pending} onClick={() => void run("complete", {}, "Case completed.")}>
              Complete case
            </Button>
          ) : (
            next.step &&
            next.kind === "do" && (
              <Button size="sm" className="shadow-xs font-medium" onClick={() => onGo(next.step!)}>
                Go to step <ArrowRight className="size-3.5" />
              </Button>
            )
          )}
        </div>
      </div>
      {c.status === "draft" && !canApprove && c.blockers.length > 0 && (
        <div className="mt-3 rounded-md border border-amber-200 bg-amber-50/70 p-2.5 text-xs dark:border-amber-900/60 dark:bg-amber-950/30">
          <p className="mb-1 font-semibold text-amber-900 dark:text-amber-200">Before approval:</p>
          <ul className="list-disc space-y-0.5 pl-4 text-amber-800/90 dark:text-amber-300/80">
            {c.blockers.map((b) => (
              <li key={b}>{b}</li>
            ))}
          </ul>
        </div>
      )}
      {c.status === "approved" && !canComplete && c.completion_blockers.length > 0 && (
        <div className="mt-3 rounded-md border border-amber-200 bg-amber-50/70 p-2.5 text-xs dark:border-amber-900/60 dark:bg-amber-950/30">
          <p className="mb-1 font-semibold text-amber-900 dark:text-amber-200">Before completion:</p>
          <ul className="list-disc space-y-0.5 pl-4 text-amber-800/90 dark:text-amber-300/80">
            {c.completion_blockers.map((b) => (
              <li key={b}>{b}</li>
            ))}
          </ul>
        </div>
      )}
      {c.approvals.length > 0 && (
        <ul className="mt-2.5 space-y-1 border-t border-border/50 pt-2 text-xs text-muted-foreground">
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

/** One step view at a time with clean top stepper and top action banner. */
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
  const [params] = useSearchParams()
  const asked = params.get("step")
  const currentIdx = next.kind === "done" ? steps.length - 1 : Math.max(0, steps.findIndex((s) => s.key === next.step))
  
  // Default to asked step, or next action step, or first step
  const initialKey = asked ?? (next.step && steps.some((s) => s.key === next.step) ? next.step : steps[currentIdx]?.key ?? steps[0]?.key ?? "")
  const [activeKey, setActiveKey] = useState<string>(initialKey)
  
  const stateOf = (i: number): StepState => (i < currentIdx ? "done" : i === currentIdx ? "current" : "upcoming")
  const activeStepIdx = Math.max(0, steps.findIndex((s) => s.key === activeKey))
  const activeStep = steps[activeStepIdx] ?? steps[0]!

  const go = (key: string) => {
    setActiveKey(key)
  }

  return (
    <div className="space-y-4">
      {/* 1. TOP PROMINENT ACTION BANNER - Always visible without scrolling */}
      <NextCard c={c} next={next} onGo={go} />

      {/* 2. INTERACTIVE STEPPER TABS */}
      <div className="flex items-center gap-1.5 overflow-x-auto rounded-lg border border-border/70 bg-card p-1.5 shadow-2xs">
        {steps.map((s, i) => {
          const state = stateOf(i)
          const isSelected = s.key === activeKey
          const badge = s.badge?.(c) ?? 0
          return (
            <button
              key={s.key}
              type="button"
              onClick={() => go(s.key)}
              className={cn(
                "flex items-center gap-2 rounded-md px-3.5 py-2 text-xs font-medium transition-all shrink-0 cursor-pointer",
                isSelected
                  ? "bg-primary text-primary-foreground shadow-xs font-semibold"
                  : state === "done"
                    ? "bg-emerald-50 text-emerald-800 hover:bg-emerald-100 dark:bg-emerald-950/40 dark:text-emerald-300"
                    : "text-muted-foreground hover:bg-muted hover:text-foreground",
              )}
            >
              <span
                className={cn(
                  "flex size-4.5 items-center justify-center rounded-full text-[10px] font-bold",
                  isSelected
                    ? "bg-primary-foreground/20 text-primary-foreground"
                    : state === "done"
                      ? "bg-emerald-200 text-emerald-900 dark:bg-emerald-800 dark:text-emerald-100"
                      : "bg-muted text-muted-foreground",
                )}
              >
                {state === "done" ? <Check className="size-2.5" /> : i + 1}
              </span>
              <span>{s.label}</span>
              {badge > 0 && (
                <span
                  className={cn(
                    "rounded-full px-1.5 py-0.2 text-[10px] font-bold",
                    isSelected ? "bg-primary-foreground/30 text-primary-foreground" : "bg-amber-100 text-amber-900 dark:bg-amber-950 dark:text-amber-200",
                  )}
                >
                  {badge}
                </span>
              )}
            </button>
          )
        })}
      </div>

      {/* 3. ACTIVE STEP WORKSPACE - Only renders the active step, zero clutter! */}
      <div className="space-y-4">
        <section aria-label={activeStep.label} className="space-y-4">
          <activeStep.Body c={c} />
        </section>

        {/* Step navigation buttons (Prev / Next) */}
        <div className="flex items-center justify-between border-t border-border/60 pt-3">
          {activeStepIdx > 0 ? (
            <Button size="sm" variant="outline" onClick={() => go(steps[activeStepIdx - 1]!.key)}>
              ← Previous: {steps[activeStepIdx - 1]!.label}
            </Button>
          ) : <div />}
          {activeStepIdx < steps.length - 1 && (
            <Button size="sm" variant="outline" onClick={() => go(steps[activeStepIdx + 1]!.key)}>
              Next: {steps[activeStepIdx + 1]!.label} →
            </Button>
          )}
        </div>

        {/* Optional Aside Content (e.g. Related Cases) */}
        {aside && <div className="pt-2">{aside}</div>}

        {/* 4. COLLAPSIBLE TECHNICAL DETAILS & AUDIT */}
        <details className="group rounded-lg border border-border/70 bg-card shadow-2xs">
          <summary className="cursor-pointer px-4 py-2.5 text-xs font-medium text-muted-foreground hover:text-foreground transition-colors flex items-center justify-between">
            <span>Documents, actions and audit details</span>
            <span className="text-[11px] text-muted-foreground/70">Click to expand</span>
          </summary>
          <div className="space-y-4 border-t border-border/60 p-4">
            <Artifacts c={c} />
            <OwnedActions c={c} />
            {!ownsPosting && <PostingTasks c={c} />}
            <CaseData c={c} />
            <CaseAudit c={c} />
          </div>
        </details>
      </div>
    </div>
  )
}
