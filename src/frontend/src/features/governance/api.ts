import type { FormField } from "@/features/agent-catalog/workspace/api"
import { apiRequest } from "@/lib/api"

export interface OrgSettings {
  allow_admin_self_approval: boolean
  updated_at: string | null
}

export interface PolicyVersion {
  version_label: string
  is_default: boolean
  /** Amounts as strings; a money map (e.g. limits per category) as name -> amount */
  values: Record<string, string | Record<string, string> | null>
  note: string | null
  created_at: string | null
  created_by: string | null
}

export interface Policy {
  agent_key: string
  agent_name: string
  fields: FormField[]
  current: PolicyVersion
}

export interface ApprovalTier {
  min_amount: string
  approvals_required: number
  approvers: { id: string; full_name: string }[] // empty = any Finance Admin
}

export interface ApprovalMatrix {
  agent_key: string
  agent_name: string
  amount_label: string | null
  tiers: ApprovalTier[]
}

export interface ApprovalTierIn {
  min_amount: string
  approvals_required: number
  approver_ids: string[]
}

export interface Delegation {
  id: string
  delegator: { id: string; full_name: string }
  delegate: { id: string; full_name: string }
  starts_at: string
  ends_at: string
  reason: string | null
  active: boolean
  cancelled_at: string | null
  created_at: string
}

export interface DelegationIn {
  delegate_id: string
  starts_at: string
  ends_at: string
  reason?: string
  delegator_id?: string
}

const GOV = "/admin/governance"

export const governanceApi = {
  settings: () => apiRequest<OrgSettings>(`${GOV}/settings`),
  setSettings: (allow: boolean) =>
    apiRequest<OrgSettings>(`${GOV}/settings`, { method: "PUT", json: { allow_admin_self_approval: allow } }),
  policies: () => apiRequest<Policy[]>(`${GOV}/policies`),
  history: (key: string) => apiRequest<PolicyVersion[]>(`${GOV}/policies/${encodeURIComponent(key)}/versions`),
  savePolicy: ({ key, values, note }: { key: string; values: Record<string, unknown>; note?: string }) =>
    apiRequest<Policy>(`${GOV}/policies/${encodeURIComponent(key)}`, { method: "PUT", json: { values, note } }),
  matrices: () => apiRequest<ApprovalMatrix[]>(`${GOV}/approval-matrix`),
  delegations: () => apiRequest<Delegation[]>(`${GOV}/delegations`),
  createDelegation: (body: DelegationIn) => apiRequest<Delegation>(`${GOV}/delegations`, { method: "POST", json: body }),
  cancelDelegation: (id: string) =>
    apiRequest<Delegation>(`${GOV}/delegations/${encodeURIComponent(id)}/cancel`, { method: "POST" }),
  saveMatrix: ({ key, tiers }: { key: string; tiers: ApprovalTierIn[] }) =>
    apiRequest<ApprovalMatrix>(`${GOV}/approval-matrix/${encodeURIComponent(key)}`, { method: "PUT", json: { tiers } }),
}
