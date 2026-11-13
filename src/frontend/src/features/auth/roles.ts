import type { Area, User, UserRole } from "./api"

export const ROLE_LABELS: Record<UserRole, string> = {
  finance_admin: "Finance Admin",
  user: "User",
}

export const AREAS: { value: Area; label: string; adminOnly: boolean }[] = [
  { value: "agent_catalog", label: "Agent Catalog", adminOnly: false },
  { value: "service_pod", label: "Service POD", adminOnly: true },
  { value: "finance_pod", label: "Finance POD", adminOnly: true },
]

/** What a new account gets unless the admin picks: everything its role allows */
export function defaultAreas(role: UserRole): Area[] {
  return AREAS.filter((a) => !a.adminOnly || role === "finance_admin").map((a) => a.value)
}

/** Finance Admin: every agent, user management and admin settings */
export function isAdmin(user: User | null | undefined): boolean {
  return user?.role === "finance_admin"
}

/** Whether a Finance Admin gave this person `area` (the PODs only ever to a Finance Admin) */
export function canUse(user: User | null | undefined, area: Area): boolean {
  if (!user) return false
  if (AREAS.find((a) => a.value === area)?.adminOnly && !isAdmin(user)) return false
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
