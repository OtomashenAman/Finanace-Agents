import { apiRequest } from "@/lib/api"

export interface OverviewKpis {
  active_agents: number
  runs_this_month: number
  pending_review: number
  high_priority: number
}

export interface WorklistItem {
  agent_key: string
  agent_name: string
  reference: string
  status: string
  priority: string
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
  kpis: OverviewKpis
  worklist: WorklistItem[]
  controls: AdminControls | null
}

export const overviewApi = {
  summary: (period?: string) =>
    apiRequest<OverviewSummary>(`/overview/summary${period ? `?period=${encodeURIComponent(period)}` : ""}`),
}
