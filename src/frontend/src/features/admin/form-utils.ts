import type { UserRole } from "@/features/auth/api"

/** aria props for a control inside <Field> */
export function describedBy(id: string, error?: string) {
  return error ? { "aria-invalid": true, "aria-describedby": `${id}-error` } : {}
}

const PREPARES = "Prepares the work; a Finance Admin signs it off."

const ROLE_HINTS: Record<UserRole, string> = {
  finance_admin: "Every Service POD workflow and every sign-off; manages users.",
  ar_specialist: `Collections: chases overdue invoices and drafts customer emails. ${PREPARES}`,
  accountant: `Bank reconciliation: matches receipts to invoices. ${PREPARES}`,
  treasury_analyst: `Cash forecasting and runway. ${PREPARES}`,
  fpa_analyst: `Variance and trend analysis with commentary. ${PREPARES}`,
  controller: `Month-end reporting, plus AR and bank oversight. ${PREPARES}`,
  user: `Only the workflows ticked below. ${PREPARES}`,
}

export function roleHint(role: UserRole): string {
  return ROLE_HINTS[role]
}
