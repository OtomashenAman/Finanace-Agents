import { apiRequest } from "@/lib/api"

export type AgentCapacity = "preparer" | "reviewer"

export interface Agent {
  key: string
  code: string
  name: string
  short_name: string
  description: string
  primary_user: string
  reviewer: string
  is_active: boolean
  my_capacities: AgentCapacity[]
}

export const agentCatalogApi = {
  list: () => apiRequest<Agent[]>("/agents"),
  get: (key: string) => apiRequest<Agent>(`/agents/${encodeURIComponent(key)}`),
  setActive: ({ key, isActive }: { key: string; isActive: boolean }) =>
    apiRequest<Agent>(`/agents/${encodeURIComponent(key)}`, { method: "PATCH", json: { is_active: isActive } }),
}
