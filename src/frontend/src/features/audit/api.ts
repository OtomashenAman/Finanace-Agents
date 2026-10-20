import { apiDownload, apiRequest } from "@/lib/api"

export type AuditCategory = "security" | "users" | "runs" | "data_sources" | "agents" | "audit"

export interface AuditPerson {
  id: string
  full_name: string
  email: string
}

export interface AuditEvent {
  id: string
  created_at: string
  event_type: string
  category: AuditCategory | null
  summary: string
  outcome: "success" | "failure"
  actor: AuditPerson | null
  subject_user: AuditPerson | null
  run: { id: string; reference: string; agent_key: string } | null
  /** Only for Finance Admins and the viewer's own actions */
  ip: string | null
  user_agent: string | null
  details: Record<string, unknown>
}

export interface AuditPage {
  items: AuditEvent[]
  next_cursor: string | null
}

export interface AuditFilters {
  category?: AuditCategory
  actorId?: string
  run?: string
  since?: string // YYYY-MM-DD
  until?: string // inclusive
  failuresOnly?: boolean
}

function query(filters: AuditFilters, cursor?: string | null): string {
  const params = new URLSearchParams()
  if (filters.category) params.set("category", filters.category)
  if (filters.actorId) params.set("actor_id", filters.actorId)
  if (filters.run) params.set("run", filters.run)
  if (filters.since) params.set("since", filters.since)
  if (filters.until) params.set("until", filters.until)
  if (filters.failuresOnly) params.set("failures_only", "true")
  if (cursor) params.set("cursor", cursor)
  const qs = params.toString()
  return qs ? `?${qs}` : ""
}

export const auditApi = {
  list: (filters: AuditFilters, cursor?: string | null) =>
    apiRequest<AuditPage>(`/audit-events${query(filters, cursor)}`),
  /** Finance Admin only */
  exportCsv: (filters: AuditFilters) => apiDownload(`/audit-events/export.csv${query(filters)}`, "audit-trail.csv"),
  timeline: (agentKey: string, runId: string) =>
    apiRequest<AuditEvent[]>(`/agents/${encodeURIComponent(agentKey)}/runs/${encodeURIComponent(runId)}/timeline`),
}

export const CATEGORY_LABELS: Record<AuditCategory, string> = {
  security: "Sign-in & security",
  users: "Users",
  runs: "Runs & approvals",
  data_sources: "Data sources",
  agents: "Agents",
  audit: "Audit exports",
}
