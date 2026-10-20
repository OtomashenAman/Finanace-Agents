import { apiRequest } from "@/lib/api"

export type LlmStatus = "ok" | "failed" | "not_configured"

export interface LlmTotals {
  calls: number
  ok: number
  failed: number
  not_configured: number
  failure_rate: number
  with_guard_warnings: number
  input_tokens: number
  output_tokens: number
  cached_tokens: number
  avg_latency_ms: number | null
  p95_latency_ms: number | null
}

export interface LlmDay {
  day: string // YYYY-MM-DD (UTC)
  calls: number
  failed: number
  input_tokens: number
  output_tokens: number
  p95_latency_ms: number | null
}

export interface LlmBreakdown {
  key: string
  label: string
  calls: number
  failed: number
  input_tokens: number
  output_tokens: number
  avg_latency_ms: number | null
}

export interface LlmCall {
  id: string
  created_at: string
  status: LlmStatus
  provider: string
  model: string
  prompt_version: string
  run: { id: string; reference: string; agent_key: string; agent_name: string }
  input_tokens: number | null
  output_tokens: number | null
  latency_ms: number | null
  guard_warnings: string[]
  error: string | null
}

export interface LlmSummary {
  days: number
  since: string
  totals: LlmTotals
  daily: LlmDay[]
  by_model: LlmBreakdown[]
  by_agent: LlmBreakdown[]
  recent_failures: LlmCall[]
  recent_calls: LlmCall[]
}

export const monitoringApi = {
  summary: (days: number) => apiRequest<LlmSummary>(`/admin/ai-monitoring?days=${days}`),
}
