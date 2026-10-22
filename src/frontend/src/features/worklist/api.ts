import { apiRequest } from "@/lib/api"

export type WorkKind =
  | "approve"
  | "changes_requested"
  | "validation_failed"
  | "ready_to_submit"
  | "draft"
  | "data_source"
  | "locked_account"
  | "password_reset"
  | "waiting"
  | "user_data_source"

export interface WorkItem {
  kind: WorkKind
  title: string
  detail: string | null
  context: string | null
  since: string
  overdue: boolean
  high_priority: boolean
  action_label: string | null // null: information only
  link: string
}

export interface Worklist {
  action: WorkItem[]
  waiting: WorkItem[]
  info: WorkItem[]
  review_sla_hours: number
  stale_draft_days: number
}

export const worklistApi = {
  get: () => apiRequest<Worklist>("/worklist"),
}
