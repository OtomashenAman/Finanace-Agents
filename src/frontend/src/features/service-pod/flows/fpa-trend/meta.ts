import type { CaseDetail } from "../../api"

export const HOME_LABEL = "Periods"

type Amount = string

export interface FpaMetric {
  period: string
  revenue: Amount
  cost_of_services: Amount
  operating_expense: Amount
  gross_profit: Amount
  total_operating_cost: Amount
  operating_profit: Amount
  margin_pct: Amount | null
  other_income: Amount | null
  other_expense: Amount | null
}

export interface FpaTxn {
  id: string
  type: string
  date: string
  period: string
  amount: Amount
  document_ref: string | null
  gl_line_id: string | null
}

export interface FpaContributor {
  counterparty: string
  change: Amount
  transactions: FpaTxn[]
}

export interface FpaCostAccount {
  account_id: string
  account: string
  classification: string
  prior: Amount
  current: Amount
  change: Amount
  contributors: FpaContributor[]
}

interface Move {
  change: Amount
  pct: Amount | null
}

export interface FpaChange {
  from: string
  to: string
  revenue: Move
  cost_of_services: Move
  operating_expense: Move
  total_operating_cost: Move
  operating_profit: Move
  margin_pp_exact: Amount | null
  margin_pp_displayed: Amount | null
  outlier: boolean
  bridge: {
    from_profit: Amount
    revenue: Amount
    cost_of_services: Amount
    operating_expense: Amount
    to_profit: Amount
    reconciles: boolean
  }
  revenue_drivers: FpaContributor[]
  cost_drivers: FpaCostAccount[]
  unexplained: { account_id: string; account: string; gl_delta: Amount; transaction_delta: Amount; difference: Amount }[]
}

export interface FpaFact {
  id: string
  label: string
  value: string
}

export interface FpaStatement {
  text: string
  fact_ids: string[]
}

export interface FpaCorrection {
  id: string
  status: "proposed" | "withdrawn"
  period: string
  evidence_gl_line_id: string
  rationale: string
  lines: { account_id: string; debit: Amount; credit: Amount; memo: string | null }[]
  proposed_by: string
  proposed_at: string
}

export interface FpaState {
  months: string[]
  business_unit: string | null
  currency: string
  basis: string
  metrics: FpaMetric[]
  changes: FpaChange[]
  yoy: { period: string; prior_period: string; revenue_prior: Amount; revenue_pct: Amount | null }[]
  seasonality: { observations: number; indices: Record<string, Amount> } | null
  mapping: { account_id: string; account: string; number: string | null; classification: string; counted_as: string }[]
  issues: { code: string; detail: string; blocking: boolean }[]
  caveats: string[]
  commentary?: {
    by: "ai" | "hand"
    author?: string
    written_at: string
    highlights: FpaStatement[]
    facts: FpaFact[]
    provenance?: { model: string; prompt_version: string }
  } | null
  recommended_actions?: (FpaStatement & { kind: "validate" | "investigate" | "approve" })[]
  mapping_review?: { by: string; at: string; note: string | null; accounts: number } | null
  corrections?: FpaCorrection[]
}

export const fpaState = (c: CaseDetail) => c.state as unknown as FpaState

export const num = (v: Amount | null | undefined) => (v === null || v === undefined ? null : Number(v))

/** "USD 540,000" (whole units: the trend pack is in currency units) */
export function amount(v: Amount | null | undefined, currency: string): string {
  const n = num(v)
  return n === null ? "-" : `${currency} ${n.toLocaleString(undefined, { maximumFractionDigits: 0 })}`
}

/** "+USD 60,000" / "−USD 8,000" */
export function signed(v: Amount, currency: string): string {
  const n = Number(v)
  const abs = Math.abs(n).toLocaleString(undefined, { maximumFractionDigits: 0 })
  return `${n > 0 ? "+" : n < 0 ? "−" : ""}${currency} ${abs}`
}

/** "+12.5%", or "undefined" for a zero baseline */
export function pct(v: Amount | null, digits = 1): string {
  if (v === null) return "undefined"
  const n = Number(v)
  return `${n > 0 ? "+" : n < 0 ? "−" : ""}${Math.abs(n).toFixed(digits)}%`
}

export function marginLabel(v: Amount | null): string {
  return v === null ? "undefined" : `${Number(v).toFixed(1)}%`
}

const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
/** "2026-09" -> "Sep 2026" (short: "Sep") */
export function monthLabel(period: string, short = false): string {
  const name = MONTHS[Number(period.slice(5, 7)) - 1] ?? period
  return short ? name : `${name} ${period.slice(0, 4)}`
}

export const blockingIssues = (s: FpaState) => s.issues.filter((i) => i.blocking)
