import { apiDownload, apiRequest } from "@/lib/api"

export interface RunFlag {
  key: string
  label: string
  severity: "block" | "review" | "info"
}

export interface RunItem {
  id: string
  position: number
  invoice_id: string
  invoice_reference: string | null
  vendor_invoice_number: string | null
  vendor_code: string
  vendor_name: string
  currency: string
  bank_name: string | null
  account_last4: string | null
  group_key: string
  invoice_total: string
  discount: string
  amount: string
  due_date: string
  discount_until: string | null
  reason: "due" | "overdue" | "discount"
  flags: RunFlag[]
  callback_status: "not_needed" | "needed" | "confirmed"
  callback_note: string | null
  callback_by_name: string | null
  callback_at: string | null
  excluded: boolean
  exclude_reason: string | null
  payment_ref: string | null
}

export interface PaymentRun {
  id: string
  reference: string
  status: "proposed" | "partly_approved" | "released" | "cancelled"
  version: number
  run_date: string
  horizon_days: number
  cash_available: string | null
  proposed_by_name: string | null
  created_at: string
  released_at: string | null
  cancelled_reason: string | null
  groups: { key: string; currency: string; count: number; total: string; discount: string }[]
  total: string
  discounts: string
  items: RunItem[]
  approvals: { name: string | null; note: string; at: string; self_approval: boolean }[]
  release_blockers: string[]
  can_approve: string | null
}

export interface RunSummary {
  id: string
  reference: string
  status: PaymentRun["status"]
  run_date: string
  count: number
  total: string
  discounts: string
  flags: number
  created_at: string
  released_at: string | null
}

export interface VendorQuery {
  id: string
  reference: string
  via: "portal" | "app"
  from_email: string
  vendor_code: string | null
  vendor_name: string | null
  invoice_number: string | null
  invoice_id: string | null
  question: string
  intent: string
  intent_source: string
  status: "answered" | "escalated" | "resolved"
  answer: string | null
  answered_by_name: string | null
  answered_at: string | null
  escalation_reason: string | null
  created_at: string
  response_minutes: number | null
}

export interface PaymentMeasures {
  payments: number
  on_time: number
  on_time_rate: number | null
  discounts_captured: string
  discounts_taken_count: number
  discounts_missed_count: number
  queries: number
  queries_answered_by_agent: number
  queries_open: number
  median_response_minutes: number | null
}

const FP = "/finance-pod"

export const paymentsApi = {
  runs: () => apiRequest<RunSummary[]>(`${FP}/payment-runs`),
  run: (id: string) => apiRequest<PaymentRun>(`${FP}/payment-runs/${id}`),
  propose: () => apiRequest<PaymentRun>(`${FP}/payment-runs`, { method: "POST" }),
  exclude: (run: PaymentRun, itemId: string, excluded: boolean, reason: string) =>
    apiRequest<PaymentRun>(`${FP}/payment-runs/${run.id}/items/${itemId}/exclude`, {
      method: "POST",
      json: { expected_version: run.version, excluded, reason },
    }),
  callback: (
    run: PaymentRun,
    itemId: string,
    body: { phone: string; source: string; contact: string; confirmed_last4: string; note: string },
  ) =>
    apiRequest<PaymentRun>(`${FP}/payment-runs/${run.id}/items/${itemId}/callback`, {
      method: "POST",
      json: { ...body, expected_version: run.version },
    }),
  approve: (run: PaymentRun, note: string) =>
    apiRequest<PaymentRun>(`${FP}/payment-runs/${run.id}/approve`, {
      method: "POST",
      json: { expected_version: run.version, note },
    }),
  cancel: (run: PaymentRun, reason: string) =>
    apiRequest<PaymentRun>(`${FP}/payment-runs/${run.id}/cancel`, {
      method: "POST",
      json: { expected_version: run.version, reason },
    }),
  remove: (ids: string[]) =>
    apiRequest<{ deleted: number }>(`${FP}/payment-runs/delete`, { method: "POST", json: { ids } }),
  bankFile: (run: PaymentRun) => apiDownload(`${FP}/payment-runs/${run.id}/bank-file`, `${run.reference}-bank-file.csv`),
  queries: (status?: string | null) =>
    apiRequest<VendorQuery[]>(status ? `${FP}/vendor-queries?status=${status}` : `${FP}/vendor-queries`),
  logQuery: (fromEmail: string, invoiceNumber: string | null, question: string) =>
    apiRequest<{ id: string; reference: string; status: string }>(`${FP}/vendor-queries`, {
      method: "POST",
      json: { from_email: fromEmail, invoice_number: invoiceNumber, question },
    }),
  reply: (id: string, answer: string) =>
    apiRequest<{ id: string }>(`${FP}/vendor-queries/${id}/reply`, { method: "POST", json: { answer } }),
  measures: () => apiRequest<PaymentMeasures>(`${FP}/measures/payments`),
  help: (fromEmail: string, invoiceNumber: string | null, question: string) =>
    apiRequest<{ reference: string; message: string }>(`/vendor-help`, {
      method: "POST",
      json: { from_email: fromEmail, invoice_number: invoiceNumber, question },
    }),
}
