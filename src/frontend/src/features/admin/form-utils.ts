import type { UserRole } from "@/features/auth/api"

/** aria props for a control inside <Field> */
export function describedBy(id: string, error?: string) {
  return error ? { "aria-invalid": true, "aria-describedby": `${id}-error` } : {}
}

const ROLE_HINTS: Record<UserRole, string> = {
  finance_admin: "Every agent and every user's runs: approves them (own runs too), manages users.",
  user: "Only the agents assigned below, on their own data. Sees only their own runs.",
}

export function roleHint(role: UserRole): string {
  return ROLE_HINTS[role]
}
