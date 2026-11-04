import type { CaseDetail } from "../../api"

export const HOME_LABEL = "Cash sources"

type Amount = string

export interface TreasuryReceipt {
  id: string
  case_id: string
  case_reference: string
  customer: string
  invoice_id: string
  invoice_number: string
  amount: Amount
  date: string
  quote: string | null
  probability: Amount
  rejected: string | null
  review: { include: boolean; probability: Amount; rationale: string | null; by: string; at: string } | null
}

export interface TreasuryOutflow {
  id: string
  date: string
  amount: Amount
  category: string
  approved: boolean
  approval_ref: string | null
}

export interface ForecastDay {
  date: string
  inflow: Amount
  outflow: Amount
  cash: Amount
  headroom: Amount
  shortfall: Amount
}

export interface ForecastResult {
  start: string
  end: string
  opening: Amount
  buffer: Amount
  inflow: Amount
  outflow: Amount
  ending_cash: Amount
  ending_shortfall: Amount
  minimum_cash: Amount
  first_breach: string | null
  max_shortfall: Amount
  weeks: { week: number; from: string; to: string; inflow: Amount; outflow: Amount; ending_cash: Amount; minimum_cash: Amount; max_shortfall: Amount }[]
  days: ForecastDay[]
}

export interface Shift {
  id: string
  event_id: string
  kind: "receipt" | "outflow"
  amount: Amount
  from_date: string
  to_date: string
  note: string
  by: string
}

export type ScenarioName = "base" | "optimistic" | "stress"

export interface TreasuryState {
  as_of: string
  currency: string
  cash: {
    as_of: string
    bank_balance: Amount
    quickbooks_cash_balance: Amount
    reconciliation_balance: Amount
    policy_buffer: Amount
    cleared: boolean
    proof_reference: string | null
  }
  issues: { code: string; detail: string; blocking: boolean }[]
  receipts: TreasuryReceipt[]
  outflows: TreasuryOutflow[]
  scenarios?: Partial<Record<"optimistic" | "stress", Shift[]>>
  results: Record<ScenarioName, ForecastResult>
}

export const treasuryState = (c: CaseDetail) => c.state as unknown as TreasuryState

export const unreviewed = (s: TreasuryState) => s.receipts.filter((r) => !r.rejected && !r.review)

export const SCENARIO_LABEL: Record<ScenarioName, string> = { base: "Base", optimistic: "Optimistic", stress: "Stress" }
