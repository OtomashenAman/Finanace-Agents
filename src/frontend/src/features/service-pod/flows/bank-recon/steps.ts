import type { CaseDetail } from "../../api"
import { caseNext, emailNext, isLocked, pendingEmails } from "../next"
import type { FlowStep, NextAction } from "../types"
import { ReceiptAndRequest, CustomerAllocation, PostingAndVerify } from "./step-bodies"

const REQUEST = "allocation_request"
const ACK = "acknowledgement"

const allocation = (c: CaseDetail) => (c.state as { allocation?: unknown }).allocation

export const BANK_STEPS: FlowStep[] = [
  { key: "request", label: "Allocation request", badge: (c) => pendingEmails(c, [REQUEST]), Body: ReceiptAndRequest },
  {
    key: "allocation",
    label: "Reply & math check",
    badge: (c) => c.review_tasks.filter((t) => t.status === "open").length,
    Body: CustomerAllocation,
  },
  {
    key: "posting",
    label: "Posting & verification",
    badge: (c) => (c.posting_tasks.some((t) => !["verified", "cancelled"].includes(t.status)) ? 1 : 0),
    Body: PostingAndVerify,
  },
]

/** The one next action, in the order the deck's bank screens run. */
export function bankNextAction(c: CaseDetail): NextAction {
  if (isLocked(c)) return caseNext(c, "posting")
  const sent = c.messages.some((m) => m.direction === "outbound" && m.purpose === REQUEST && m.status === "sent")
  if (!sent)
    return (
      emailNext(c, [REQUEST], "request", "allocation request") ?? {
        text: "Ask the customer which invoices the payment covers",
        step: "request",
        kind: "do",
      }
    )
  if (!c.messages.some((m) => m.direction === "inbound"))
    return { text: "Waiting for the customer's reply; import it here when it arrives", step: "allocation", kind: "do" }
  if (!allocation(c)) return { text: "Record the customer's allocation from their reply", step: "allocation", kind: "do" }
  const open = c.review_tasks.filter((t) => t.status === "open").length
  if (open) return { text: `Settle ${open} open review task(s)`, step: "allocation", kind: "do" }
  if (c.status === "draft") return caseNext(c, "allocation")
  const task = c.posting_tasks.find((t) => t.kind === "receive_payment")
  if (!task) return { text: "Queue the manual QuickBooks posting", step: "posting", kind: "do" }
  if (task.status === "proposed") return { text: "Post it in QuickBooks and record the transaction ID", step: "posting", kind: "do" }
  if (task.status !== "verified")
    return { text: "Verify the posting against a fresh QuickBooks export", step: "posting", kind: "do" }
  const ack = emailNext(c, [ACK], "posting", "acknowledgement")
  if (ack) return ack
  if (!c.messages.some((m) => m.purpose === ACK && m.status === "sent"))
    return { text: "Confirm to the customer how the payment was applied", step: "posting", kind: "do" }
  return caseNext(c, "posting")
}
