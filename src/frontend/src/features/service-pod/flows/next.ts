import type { CaseDetail, Message } from "../api"
import type { NextAction } from "./types"

const LOCKED = ["completed", "cancelled"]

/** Where an outbound email of these purposes stands, as the next action (none: no email). */
export function emailNext(c: CaseDetail, purposes: string[], step: string, what: string): NextAction | undefined {
  const mails = c.messages.filter((m) => m.direction === "outbound" && purposes.includes(m.purpose))
  const last: Message | undefined = mails[mails.length - 1]
  if (!last) return undefined
  switch (last.status) {
    case "draft":
      return { text: `Check and send the ${what}`, step, kind: "do" }
    case "sending":
      return { text: `The ${what} is being sent`, step, kind: "wait" }
    case "send_unknown":
      return { text: `Reconcile the ${what}: its send outcome is unknown`, step, kind: "do" }
    case "send_failed":
      return { text: `Fix the ${what} and send it again`, step, kind: "do" }
    default:
      return undefined
  }
}

/** The case's own gates once the work is done: approve, then complete. */
export function caseNext(c: CaseDetail, step: string): NextAction {
  const a = c.allowed_actions
  if (LOCKED.includes(c.status)) return { text: `The case is ${c.status}.`, kind: "done" }
  if (a.approve === null) return { text: "Approve the case", step, kind: "do" }
  if (a.complete === null) return { text: "Complete the case", step, kind: "do" }
  if (c.status === "approved") return { text: c.completion_blockers[0] ?? "Complete the case", step, kind: "wait" }
  return { text: c.blockers[0] ?? "Nothing to do right now", step, kind: "wait" }
}

export const isLocked = (c: CaseDetail) => LOCKED.includes(c.status)

/** Emails still to send or settle (draft, failed, unclear send) */
export function pendingEmails(c: CaseDetail, purposes: string[]): number {
  return c.messages.filter(
    (m) => m.direction === "outbound" && purposes.includes(m.purpose) && ["draft", "send_unknown", "send_failed"].includes(m.status),
  ).length
}
