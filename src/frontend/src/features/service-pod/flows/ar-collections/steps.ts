import type { CaseDetail } from "../../api"
import { caseNext, emailNext, isLocked, pendingEmails } from "../next"
import type { FlowStep, NextAction } from "../types"
import { InvoicesAndEmail, CustomerReply, ScheduleAndClose } from "./step-bodies"

const REQUEST = "payment_schedule_request"
const FOLLOW_UP = "follow_up"

export const AR_STEPS: FlowStep[] = [
  { key: "email", label: "Email composer", badge: (c) => pendingEmails(c, [REQUEST]), Body: InvoicesAndEmail },
  { key: "reply", label: "Reply understanding", badge: (c) => c.review_tasks.filter((t) => t.status === "open").length, Body: CustomerReply },
  { key: "close", label: "Finance action queue", badge: (c) => c.commitments.filter((x) => x.status === "proposed").length, Body: ScheduleAndClose },
]

/** The one next action, in the order the deck's screens run. */
export function arNextAction(c: CaseDetail): NextAction {
  if (isLocked(c)) return caseNext(c, "close")
  const sent = c.messages.some((m) => m.direction === "outbound" && m.purpose === REQUEST && m.status === "sent")
  if (!sent) {
    const mail = emailNext(c, [REQUEST], "email", "payment request email")
    return mail ?? { text: "Draft the payment request email to the customer", step: "email", kind: "do" }
  }
  const followUp = emailNext(c, [FOLLOW_UP], "close", "follow-up reply")
  if (followUp?.kind === "do") return followUp
  if (!c.messages.some((m) => m.direction === "inbound"))
    return { text: "Waiting for the customer's reply; import it here when it arrives", step: "reply", kind: "do" }
  const open = c.review_tasks.filter((t) => t.status === "open")
  if (open.length)
    return { text: `Settle ${open.length} open review task(s): dates only from the customer, documents once approved`, step: "reply", kind: "do" }
  const proposed = c.commitments.filter((x) => x.status === "proposed").length
  if (proposed) return { text: `Decide ${proposed} proposed commitment(s)`, step: "close", kind: "do" }
  return caseNext(c, "close")
}
