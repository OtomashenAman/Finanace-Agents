import { useState } from "react"
import { Link, useSearchParams } from "react-router"
import { ArrowRight, CircleCheck, Hourglass } from "lucide-react"

import { Button } from "@/components/ui/button"
import { cn } from "@/lib/utils"

import type { CaseDetail, WorkflowKey } from "../api"
import { useCases } from "../hooks"
import { WORKFLOW_SLUG } from "../labels"
import type { FlowStep, NextAction } from "../flows/types"
import { CaseData, PostingTasks } from "./case-extras"
import { Artifacts } from "./case-messages"
import { OwnedActions } from "./case-sections"

const DETAILS = "details"

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
        const to = waiting.length === 1 ? `/pod/cases/${waiting[0]!.id}?step=${s.key}` : `/pod/${slug}/cases?stage=${s.key}`
        return (
          <Link key={s.key} to={to} className={stepClass(false)} title={waiting.map((c) => `${c.reference} ${c.title}`).join(", ")}>
            {body}
          </Link>
        )
      })}
    </nav>
  )
}

/** The one next thing, for this viewer, with a jump to the step where it happens. */
function NextBar({ next, onGo }: { next: NextAction; onGo: (step: string) => void }) {
  const Icon = next.kind === "done" ? CircleCheck : next.kind === "wait" ? Hourglass : ArrowRight
  return (
    <div
      className={cn(
        "flex flex-wrap items-center gap-3 rounded-lg border px-4 py-3 text-sm",
        next.kind === "do" ? "border-primary/40 bg-primary/5" : "bg-card",
      )}
    >
      <Icon className={cn("size-4", next.kind === "do" ? "text-primary" : "text-muted-foreground")} aria-hidden />
      <span>
        <span className="font-semibold">{next.kind === "do" ? "Next: " : next.kind === "wait" ? "Waiting: " : ""}</span>
        {next.text}
      </span>
      {next.step && next.kind === "do" && (
        <Button size="sm" className="ml-auto" onClick={() => onGo(next.step!)}>
          Go
        </Button>
      )}
    </div>
  )
}

/** A case as steps (deck screens), plus a Details tab for documents, actions and data. */
export function CaseSteps({
  c,
  steps,
  next,
  ownsPosting,
  home,
}: {
  c: CaseDetail
  steps: FlowStep[]
  next: NextAction
  ownsPosting: boolean
  /** The workflow's home screen, shown as step 1 (back to the list) */
  home?: { label: string; to: string }
}) {
  // Opens on the step asked for (from a worklist), else where the work is; then the viewer's choice sticks
  const [params] = useSearchParams()
  const asked = params.get("step")
  const [active, setActive] = useState(steps.some((s) => s.key === asked) ? asked! : (next.step ?? steps[0]!.key))
  const current = steps.find((s) => s.key === active)
  const tab = (key: string) => stepClass(active === key)
  const first = home ? 2 : 1
  return (
    <div className="space-y-4">
      <NextBar next={next} onGo={setActive} />
      <nav aria-label="Case steps" className="flex overflow-x-auto border-b">
        {home && (
          <Link to={home.to} className={tab("")} title={`Back to ${home.label}`}>
            <Num n={1} on={false} />
            {home.label}
          </Link>
        )}
        {steps.map((s, i) => {
          const count = s.badge?.(c) ?? 0
          return (
            <button key={s.key} type="button" className={tab(s.key)} onClick={() => setActive(s.key)} aria-current={active === s.key ? "step" : undefined}>
              <Num n={i + first} on={active === s.key} />
              {s.label}
              {count > 0 && <span className="rounded-full bg-amber-100 px-1.5 text-xs text-amber-900">{count}</span>}
            </button>
          )
        })}
        <button type="button" className={cn(tab(DETAILS), "ml-auto")} onClick={() => setActive(DETAILS)}>
          Details
        </button>
      </nav>
      <div className="space-y-6">
        {current ? (
          <current.Body c={c} />
        ) : (
          <>
            <Artifacts c={c} />
            <OwnedActions c={c} />
            {!ownsPosting && <PostingTasks c={c} />}
            <CaseData c={c} />
          </>
        )}
      </div>
    </div>
  )
}
