import type { CaseDetail } from "../../api"
import { caseNext, emailNext, isLocked } from "../next"
import type { FlowStep, NextAction } from "../types"
import { marginLabel, monthLabel } from "../fpa-trend/meta"
import { controllerSigned, reportState } from "./meta"
import { CfoApproval, ControllerReview, MonthAndControls, StatementsAndVariance } from "./step-bodies"

export const REPORTING_STEPS: FlowStep[] = [
  {
    key: "controls",
    label: "Month & controls",
    badge: (c) => reportState(c).issues.filter((i) => i.blocking).length + c.review_tasks.filter((t) => t.kind === "scope" && t.status === "open").length,
    summary: (c) => {
      const s = reportState(c)
      return `${monthLabel(s.report_month)} against ${monthLabel(s.prior_month)} · every control passed`
    },
    Body: MonthAndControls,
  },
  {
    key: "statements",
    label: "Statements & variance",
    summary: (c) => {
      const s = reportState(c)
      const cur = s.metrics.at(-1)
      return cur ? `Margin ${marginLabel(cur.margin_pct)} · balance sheet balanced` : null
    },
    Body: StatementsAndVariance,
  },
  {
    key: "controller",
    label: "Controller review",
    badge: (c) => c.review_tasks.filter((t) => t.status === "open" && t.blocking && t.kind !== "scope").length,
    summary: (c) => {
      const a = c.approvals.filter((x) => x.valid && x.capacity === "Controller").at(-1)
      return a ? `Signed off as Controller by ${a.user.name}` : "Commentary written"
    },
    Body: ControllerReview,
  },
  {
    key: "cfo",
    label: "CFO approval & pack",
    Body: CfoApproval,
  },
]

export function reportingNextAction(c: CaseDetail): NextAction {
  if (isLocked(c)) return caseNext(c, "cfo")
  const s = reportState(c)
  const issues = s.issues.filter((i) => i.blocking).length
  if (issues)
    return { text: `Settle ${issues} control issue${issues > 1 ? "s" : ""}: correct the source and refresh (nothing is filled in)`, step: "controls", kind: "do", phase: "review" }
  if (c.review_tasks.some((t) => t.kind === "scope" && t.status === "open"))
    return { text: "Settle the AR aging date: evidence, or keep it as a disclosed limitation", step: "controls", kind: "do", phase: "review" }
  if (!s.commentary) return { text: "Review the statements and variances, then draft the pack commentary", step: "statements", kind: "do", phase: "analysis" }
  const refresh = c.blockers.find((b) => b.includes("refresh")) ?? c.completion_blockers.find((b) => b.includes("refresh"))
  if (refresh) return { text: refresh, step: "controller", kind: "do", phase: "review" }
  const open = c.review_tasks.filter((t) => t.status === "open" && t.blocking).length
  if (open) return { text: `Settle ${open} open review task${open > 1 ? "s" : ""}`, step: "controller", kind: "do", phase: "review" }
  if (c.status === "draft" && c.allowed_actions.approve === null) {
    return controllerSigned(c)
      ? { text: "The Controller has signed off: approve the same content as the CFO", step: "cfo", kind: "do", phase: "ready" }
      : { text: "Review the evidence and commentary, then sign off as the Controller", step: "controller", kind: "do", phase: "ready" }
  }
  if (c.status === "approved") {
    if (c.completion_blockers.some((b) => b.includes("PDF pack")))
      return { text: "Export the signed-off PDF management pack", step: "cfo", kind: "do", phase: "approved" }
    const mail = emailNext(c, ["pack_distribution"], "cfo", "pack email")
    if (mail) return mail
  }
  return caseNext(c, "cfo")
}
