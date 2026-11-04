import type { CaseDetail } from "../../api"
import { caseNext, isLocked } from "../next"
import type { FlowStep, NextAction } from "../types"
import { blockingIssues, fpaState, marginLabel, monthLabel } from "./meta"
import { PeriodAndData, SignOff, TrendsAndDrivers } from "./step-bodies"

export const FPA_STEPS: FlowStep[] = [
  {
    key: "data",
    label: "Period & data",
    badge: (c) => blockingIssues(fpaState(c)).length,
    summary: (c) => {
      const s = fpaState(c)
      return `${monthLabel(s.months[0]!)} to ${monthLabel(s.months[s.months.length - 1]!)} · every check passed${s.mapping_review ? " · mapping reviewed" : ""}`
    },
    Body: PeriodAndData,
  },
  {
    key: "analysis",
    label: "Trends & drivers",
    summary: (c) => {
      const s = fpaState(c)
      const last = s.metrics[s.metrics.length - 1]
      return last ? `${monthLabel(last.period)} margin ${marginLabel(last.margin_pct)} · ${s.changes.length} month-on-month comparisons` : null
    },
    Body: TrendsAndDrivers,
  },
  {
    key: "signoff",
    label: "Finance Head sign-off",
    badge: (c) => c.review_tasks.filter((t) => t.status === "open" && t.blocking).length,
    summary: (c) => {
      const a = c.approvals.filter((x) => x.valid).at(-1)
      return a ? `Signed off as ${a.capacity} by ${a.user.name}` : `Case ${c.status}`
    },
    Body: SignOff,
  },
]

/** The one next action: data issues, then commentary, then the sign-off and any correction. */
export function fpaNextAction(c: CaseDetail): NextAction {
  if (isLocked(c)) return caseNext(c, "signoff")
  const s = fpaState(c)
  const issues = blockingIssues(s).length
  if (issues)
    return {
      text: `Settle ${issues} data issue${issues > 1 ? "s" : ""}: correct the source and refresh the case (nothing is filled in)`,
      step: "data",
      kind: "do",
      phase: "review",
    }
  if (!s.commentary)
    return { text: "Review the trends and drivers, then draft the Finance Head commentary", step: "analysis", kind: "do", phase: "analysis" }
  const refresh = c.blockers.find((b) => b.includes("refresh")) ?? c.completion_blockers.find((b) => b.includes("refresh"))
  if (refresh) return { text: refresh, step: "signoff", kind: "do", phase: "review" }
  const open = c.review_tasks.filter((t) => t.status === "open" && t.blocking).length
  if (open) return { text: `Settle ${open} open review task${open > 1 ? "s" : ""}`, step: "signoff", kind: "do", phase: "review" }
  if (c.status === "approved") {
    const pending = (s.corrections ?? []).find(
      (x) => x.status === "proposed" && !c.posting_tasks.some((t) => t.reference === `${c.reference}-${x.id}`),
    )
    if (pending) return { text: `Queue correction ${pending.id} for the Finance Admin to post`, step: "signoff", kind: "do", phase: "posting" }
    const task = c.posting_tasks.find((t) => !["verified", "cancelled"].includes(t.status))
    if (task)
      return {
        text: task.status === "proposed" ? `Post journal ${task.reference} in QuickBooks and record its number` : `Verify ${task.reference} against a fresh source`,
        step: "signoff",
        kind: "do",
        phase: "posting",
      }
  }
  if (c.status === "draft" && c.allowed_actions.approve === null)
    return { text: "Sign off the findings and commentary as the Finance Head", step: "signoff", kind: "do", phase: "ready" }
  return caseNext(c, "signoff")
}
