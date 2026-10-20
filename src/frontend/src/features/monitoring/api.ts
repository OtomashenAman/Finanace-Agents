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

export interface QueueJob {
  id: string
  kind: string
  status: "queued" | "running" | "succeeded" | "failed"
  attempts: number
  max_attempts: number
  last_error: string | null
  created_at: string
  run_after: string
  finished_at: string | null
  run_reference: string | null
  run_link: string | null
}

export interface QueueSummary {
  queued: number
  running: number
  failed: number
  succeeded_24h: number
  oldest_queued_seconds: number | null
  by_kind: { kind: string; queued: number; running: number; succeeded: number; failed: number }[]
  failures: QueueJob[]
  retrying: QueueJob[]
}

export const jobsApi = {
  summary: () => apiRequest<QueueSummary>("/admin/jobs"),
  retry: (id: string) => apiRequest<QueueJob>(`/admin/jobs/${encodeURIComponent(id)}/retry`, { method: "POST" }),
}
