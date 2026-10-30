import type { PromiseRow } from "../../api"

export const HOME_LABEL = "Portfolio"

/** "Overdue 2 d", "Due tomorrow", "In 10 d", "Received" */
export function promiseLabel(p: Pick<PromiseRow, "state" | "days_until">): string {
  if (p.state === "received") return "Received"
  if (p.days_until < 0) return `Overdue ${-p.days_until} d`
  if (p.days_until === 0) return "Due today"
  if (p.days_until === 1) return "Due tomorrow"
  return `In ${p.days_until} d`
}

/** Days from today to a promise date (negative: overdue); the server's view also knows
 *  whether cash came in, the case page only the date. */
export function daysUntil(isoDate: string): number {
  const today = new Date()
  const start = Date.UTC(today.getFullYear(), today.getMonth(), today.getDate())
  const [y, mo, d] = isoDate.split("-").map(Number)
  return Math.round((Date.UTC(y!, mo! - 1, d!) - start) / 86_400_000)
}
