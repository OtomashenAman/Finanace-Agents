import type { CaseDetail } from "../../api"
import type { FpaState } from "../fpa-trend/meta"

export const HOME_LABEL = "Report months"

type Amount = string

export interface ReportState extends FpaState {
  report_month: string
  prior_month: string
  balance_sheets: Record<string, { assets: Amount; liabilities: Amount; equity: Amount; difference: Amount; balanced: boolean; report_id: string } | null>
  close: { status: "Open" | "Closed" | null; required_checks: string[] }
  aging: {
    as_of: string
    month_end: string
    matches_month_end: boolean
    buckets: { label: string; amount: Amount; count: number }[]
    total: Amount
  }
  controls: { key: string; label: string; status: "pass" | "fail"; detail: string }[]
}

export const reportState = (c: CaseDetail) => c.state as unknown as ReportState

/** The Controller has signed the current content (the case then waits for the CFO) */
export const controllerSigned = (c: CaseDetail) => c.approvals.some((a) => a.valid && a.capacity === "Controller")
