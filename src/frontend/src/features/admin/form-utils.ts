import type { UserRole } from "@/features/auth/api"
import { ApiError } from "@/lib/api"

export function errorMessage(error: unknown, fallback: string): string {
  return error instanceof ApiError ? error.message : fallback
}

/** aria props for a control inside <Field> */
export function describedBy(id: string, error?: string) {
  return error ? { "aria-invalid": true, "aria-describedby": `${id}-error` } : {}
}

const ROLE_HINTS: Record<UserRole, string> = {
  finance_admin: "Every agent (prepare and approve, including own runs), user management and settings.",
  user: "Only the agents and capacities assigned below.",
}

export function roleHint(role: UserRole): string {
  return ROLE_HINTS[role]
}
