import type { RunSummary } from "@/features/agent-catalog/workspace/api"
import { apiRequest } from "@/lib/api"

export interface ApprovalItem extends RunSummary {
  submitted_at: string | null
  decided_at: string | null
}

export const approvalsApi = {
  /** Pending (oldest first) or decided (newest first), across agents */
  list: (decided: boolean) => apiRequest<ApprovalItem[]>(decided ? "/approvals?decided=true" : "/approvals"),
}
