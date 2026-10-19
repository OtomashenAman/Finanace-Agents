import type { User, UserRole } from "./api"

export const ROLE_LABELS: Record<UserRole, string> = {
  finance_admin: "Finance Admin",
  preparer: "Preparer",
  reviewer: "Reviewer",
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
