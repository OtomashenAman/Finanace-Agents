import type { RunStatus } from "@/features/agent-catalog/workspace/api"
import { apiRequest } from "@/lib/api"

export interface OverviewKpis {
  active_agents: number
  runs_this_month: number
  pending_review: number
  high_priority: number
}

export interface WorklistItem {
  run_id: string
  agent_key: string
  agent_name: string
  reference: string
  entity_code: string | null
  owner: string
  exceptions: number
  status: RunStatus
  status_label: string
  priority: "normal" | "high"
  created_at: string
}

export interface AdminControls {
  entity: string
  period_label: string
  review_sla_hours: number
  connector_health: string
  model_execution: string
}

export interface OverviewSummary {
  period: string
  entity: string
  entity_id: string | null
  kpis: OverviewKpis
  worklist: WorklistItem[]
  controls: AdminControls | null
}

export interface OverviewFilters {
  period?: string
  entityId?: string | null
  agent?: string | null
  priority?: "high" | "normal" | null
}

export const overviewApi = {
  summary: ({ period, entityId, agent, priority }: OverviewFilters = {}) => {
    const params = new URLSearchParams()
    if (period) params.set("period", period)
    if (entityId) params.set("entity_id", entityId)
    if (agent) params.set("agent", agent)
    if (priority) params.set("priority", priority)
    const qs = params.toString()
    return apiRequest<OverviewSummary>(`/overview/summary${qs ? `?${qs}` : ""}`)
  },
}
