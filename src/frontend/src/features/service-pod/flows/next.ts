import type { CaseDetail, Message } from "../api"
import { formatDateTime } from "../labels"
import type { CasePhase, NextAction } from "./types"

const LOCKED = ["completed", "cancelled"]

/** Where an outbound email of these purposes stands, as the next action (none: no email). */
export function emailNext(c: CaseDetail, purposes: string[], step: string, what: string): NextAction | undefined {
  const mails = c.messages.filter((m) => m.direction === "outbound" && purposes.includes(m.purpose))
  const last: Message | undefined = mails[mails.length - 1]
  if (!last) return undefined
  switch (last.status) {
    case "draft":
      return { text: `Check and send the ${what}`, step, kind: "do", phase: "compose" }
    case "sending":
      return { text: `The ${what} is being sent`, step, kind: "wait", phase: "compose" }
    case "send_unknown":
      return { text: `Reconcile the ${what}: its send outcome is unknown`, step, kind: "do", phase: "review" }
    case "send_failed":
      return { text: `Fix the ${what} and send it again`, step, kind: "do", phase: "compose" }
    default:
      return undefined
  }
}

/** The case's own gates once the work is done: approve, then complete. */
export function caseNext(c: CaseDetail, step: string): NextAction {
  const a = c.allowed_actions
  if (LOCKED.includes(c.status)) return { text: `The case is ${c.status}.`, kind: "done", phase: c.status as CasePhase }
  if (a.approve === null) return { text: "Approve the case", step, kind: "do", phase: "ready" }
  if (a.complete === null) return { text: "Complete the case", step, kind: "do", phase: "approved" }
  if (c.status === "approved")
    return { text: c.completion_blockers[0] ?? "Complete the case", step, kind: "wait", phase: "approved" }
  return { text: c.blockers[0] ?? "Nothing to do right now", step, kind: "wait", phase: "review" }
}

/** "Sent to x@y on Nov 2, 12:39 PM" for the last sent email of these purposes */
export function sentSummary(c: CaseDetail, purposes: string[]): string | null {
  const sent = c.messages.filter((m) => m.direction === "outbound" && purposes.includes(m.purpose) && m.status === "sent")
  const last = sent[sent.length - 1]
  return last ? `Sent to ${last.to_email} on ${formatDateTime(last.sent_at)}` : null
}

export const isLocked = (c: CaseDetail) => LOCKED.includes(c.status)

/** Emails still to send or settle (draft, failed, unclear send) */
export function pendingEmails(c: CaseDetail, purposes: string[]): number {
  return c.messages.filter(
    (m) => m.direction === "outbound" && purposes.includes(m.purpose) && ["draft", "send_unknown", "send_failed"].includes(m.status),
  ).length
}
