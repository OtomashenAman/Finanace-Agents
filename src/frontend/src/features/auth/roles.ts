import type { Area, PodWorkflow, User, UserRole } from "./api"

/** Agent Catalog and Finance POD are switched off for now (nav, routes, admin sections).
 *  Set to true to bring them back. */
export const CATALOG_AND_FINANCE_POD_ENABLED = false

export const ROLE_LABELS: Record<UserRole, string> = {
  finance_admin: "Finance Admin",
  ar_specialist: "AR Specialist",
  accountant: "Accountant",
  treasury_analyst: "Treasury Analyst",
  fpa_analyst: "FP&A Analyst",
  controller: "Controller",
  user: "User",
}

/** Service POD workflows, in the POD's order */
export const POD_WORKFLOWS: { value: PodWorkflow; label: string }[] = [
  { value: "ar_collections", label: "AR Collections" },
  { value: "bank_recon", label: "Bank Reconciliation" },
  { value: "fpa_trend", label: "FP&A Trend" },
  { value: "treasury", label: "Treasury Forecast" },
  { value: "reporting", label: "Financial Reporting" },
]

/** What each role starts with (mirrors ROLE_WORKFLOWS in src/app/auth/models.py) */
export const ROLE_WORKFLOWS: Record<UserRole, PodWorkflow[]> = {
  finance_admin: POD_WORKFLOWS.map((w) => w.value),
  ar_specialist: ["ar_collections"],
  accountant: ["bank_recon"],
  treasury_analyst: ["treasury"],
  fpa_analyst: ["fpa_trend"],
  controller: ["ar_collections", "bank_recon", "reporting"],
  user: [],
}

export function workflowLabel(workflow: PodWorkflow): string {
  return POD_WORKFLOWS.find((w) => w.value === workflow)?.label ?? workflow
}

export const AREAS: { value: Area; label: string; adminOnly: boolean }[] = [
  { value: "agent_catalog", label: "Agent Catalog", adminOnly: false },
  { value: "service_pod", label: "Service POD", adminOnly: false },
  { value: "finance_pod", label: "Finance POD", adminOnly: true },
]

/** What a new account gets unless the admin picks: everything its role allows */
export function defaultAreas(role: UserRole): Area[] {
  return AREAS.filter((a) => !a.adminOnly || role === "finance_admin").map((a) => a.value)
}

/** Finance Admin: every workflow, every sign-off, user management and admin settings */
export function isAdmin(user: User | null | undefined): boolean {
  return user?.role === "finance_admin"
}

/** Whether this person has `area` (Finance POD only for a Finance Admin; the Service POD
 *  only with at least one workflow) */
export function canUse(user: User | null | undefined, area: Area): boolean {
  if (!user) return false
  if (AREAS.find((a) => a.value === area)?.adminOnly && !isAdmin(user)) return false
  if (area === "service_pod" && !(user.pod_workflows ?? []).length) return false
  return (user.areas ?? []).includes(area)
}

/** "Finance Admin" -> "FA" (shown in the header avatar, as in the mock-ups) */
export function initials(user: User): string {
  return user.full_name
    .split(/\s+/)
    .filter(Boolean)
    .slice(0, 2)
    .map((part) => part[0]!.toUpperCase())
    .join("")
}
