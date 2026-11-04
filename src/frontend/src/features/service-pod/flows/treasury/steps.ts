import type { CaseDetail } from "../../api"
import { amount } from "../fpa-trend/meta"
import { caseNext, isLocked } from "../next"
import type { FlowStep, NextAction } from "../types"
import { treasuryState, unreviewed } from "./meta"
import { Forecast, MitigationAndCfo, OpeningCash, ReceiptsAndOutflows } from "./step-bodies"

export const TREASURY_STEPS: FlowStep[] = [
  {
    key: "cash",
    label: "Opening cash",
    badge: (c) => treasuryState(c).issues.filter((i) => i.blocking).length,
    summary: (c) => {
      const s = treasuryState(c)
      return `${amount(s.cash.bank_balance, s.currency)} cleared and reconciled · buffer ${amount(s.cash.policy_buffer, s.currency)}`
    },
    Body: OpeningCash,
  },
  {
    key: "receipts",
    label: "Receipts review",
    badge: (c) => unreviewed(treasuryState(c)).length,
    summary: (c) => {
      const s = treasuryState(c)
      const used = s.receipts.filter((r) => r.review?.include)
      return `${used.length} of ${s.receipts.length} tranches included · ${s.outflows.filter((o) => o.approved).length} approved outflows`
    },
    Body: ReceiptsAndOutflows,
  },
  {
    key: "forecast",
    label: "13-week forecast",
    summary: (c) => {
      const s = treasuryState(c)
      const b = s.results.base
      return `Base ends at ${amount(b.ending_cash, s.currency)}${b.first_breach ? ` · below the buffer from ${b.first_breach}` : ""}`
    },
    Body: Forecast,
  },
  { key: "cfo", label: "Mitigation & CFO", Body: MitigationAndCfo },
]

export function treasuryNextAction(c: CaseDetail): NextAction {
  if (isLocked(c)) return caseNext(c, "cfo")
  const s = treasuryState(c)
  const issues = s.issues.filter((i) => i.blocking).length
  if (issues) return { text: "Fix the opening cash: import a source whose cash is cleared and reconciled", step: "cash", kind: "do", phase: "review" }
  const waiting = unreviewed(s).length
  if (waiting) return { text: `Review ${waiting} receipt tranche${waiting > 1 ? "s" : ""}: include with a probability, or leave out`, step: "receipts", kind: "do", phase: "review" }
  const mitigation = c.blockers.find((b) => b.includes("mitigation"))
  if (mitigation) return { text: mitigation, step: "cfo", kind: "do", phase: "review" }
  if (c.status === "draft" && c.allowed_actions.approve === null)
    return c.next_signoff === "CFO"
      ? { text: "The Treasury Head has signed off: give the CFO's final cash-plan approval", step: "cfo", kind: "do", phase: "ready" }
      : { text: "Review the forecast and scenarios, then sign off as the Treasury Head", step: "forecast", kind: "do", phase: "ready" }
  return caseNext(c, "cfo")
}
