import type { RunSummary } from "@/features/agent-catalog/workspace/api"
import { apiRequest } from "@/lib/api"

export interface ApprovalItem extends RunSummary {
  submitted_at: string | null
  decided_at: string | null
}

export const approvalsApi = {
  /** Pending (oldest first) or decided (newest first), across agents */
  list: (decided: boolean, entityId?: string | null) => {
    const params = new URLSearchParams()
    if (decided) params.set("decided", "true")
    if (entityId) params.set("entity_id", entityId)
    const qs = params.toString()
    return apiRequest<ApprovalItem[]>(`/approvals${qs ? `?${qs}` : ""}`)
  },
}
