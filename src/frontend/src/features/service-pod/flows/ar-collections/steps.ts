import type { CaseDetail } from "../../api"
import { formatDateTime } from "../../labels"
import { caseNext, emailNext, isLocked, pendingEmails, sentSummary } from "../next"
import type { FlowStep, NextAction } from "../types"
import { InvoicesAndEmail, CustomerReply, ScheduleAndClose } from "./step-bodies"

const REQUEST = "payment_schedule_request"
const FOLLOW_UP = "follow_up"

export const AR_STEPS: FlowStep[] = [
  {
    key: "email",
    label: "Send email",
    badge: (c) => pendingEmails(c, [REQUEST]),
    summary: (c) => sentSummary(c, [REQUEST]),
    Body: InvoicesAndEmail,
  },
  {
    key: "reply",
    label: "Customer reply",
    badge: (c) => c.review_tasks.filter((t) => t.status === "open").length,
    summary: (c) => {
      const replies = c.messages.filter((m) => m.direction === "inbound")
      if (!replies.length) return "No reply yet."
      const last = replies[replies.length - 1]!
      const open = c.review_tasks.filter((t) => t.status === "open").length
      return `${replies.length} repl${replies.length > 1 ? "ies" : "y"}, last ${formatDateTime(last.received_at ?? last.created_at)}${open ? ` · ${open} open review task${open > 1 ? "s" : ""}` : " · all settled"}`
    },
    Body: CustomerReply,
  },
  {
    key: "close",
    label: "Approve & close",
    badge: (c) => c.commitments.filter((x) => x.status === "proposed").length,
    summary: (c) => {
      const approved = c.commitments.filter((x) => x.status === "approved").length
      return `${approved} approved payment commitment${approved === 1 ? "" : "s"} · case ${c.status}`
    },
    Body: ScheduleAndClose,
  },
]

/** The one next action, in the order the deck's screens run. */
export function arNextAction(c: CaseDetail): NextAction {
  if (isLocked(c)) return caseNext(c, "close")
  const sent = c.messages.some((m) => m.direction === "outbound" && m.purpose === REQUEST && m.status === "sent")
  if (!sent) {
    const mail = emailNext(c, [REQUEST], "email", "payment request email")
    return mail ?? { text: "Draft the payment request email to the customer", step: "email", kind: "do", phase: "compose" }
  }
  const followUp = emailNext(c, [FOLLOW_UP], "close", "follow-up reply")
  if (followUp?.kind === "do") return followUp
  if (!c.messages.some((m) => m.direction === "inbound"))
    return {
      text: "Waiting for the customer's reply: it is picked up from the mailbox automatically",
      step: "reply",
      kind: "wait",
      phase: "waiting",
    }
  const open = c.review_tasks.filter((t) => t.status === "open")
  if (open.length)
    return {
      text: `Settle ${open.length} open review task${open.length > 1 ? "s" : ""}: dates only from the customer, documents once approved`,
      step: "reply",
      kind: "do",
      phase: "review",
    }
  const proposed = c.commitments.filter((x) => x.status === "proposed").length
  if (proposed)
    return { text: `Decide ${proposed} proposed commitment${proposed > 1 ? "s" : ""}`, step: "close", kind: "do", phase: "review" }
  return caseNext(c, "close")
}
