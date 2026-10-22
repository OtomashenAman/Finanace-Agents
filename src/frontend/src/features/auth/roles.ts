import type { User, UserRole } from "./api"

export const ROLE_LABELS: Record<UserRole, string> = {
  finance_admin: "Finance Admin",
  user: "User",
}

/** Finance Admin: every agent, user management and admin settings */
export function isAdmin(user: User | null | undefined): boolean {
  return user?.role === "finance_admin"
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
