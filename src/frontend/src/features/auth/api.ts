import { ApiError, apiRequest } from "@/lib/api"

import type { LoginFormValues } from "./schema"

export type UserRole =
  | "finance_admin"
  | "ar_specialist"
  | "accountant"
  | "treasury_analyst"
  | "fpa_analyst"
  | "controller"
  | "user"

/** The parts of the app a Finance Admin gives each person (the Finance POD only to Finance Admins) */
export type Area = "agent_catalog" | "service_pod" | "finance_pod"

/** Service POD workflows (WorkflowKey in src/app/service_pod/core/workflows.py) */
export type PodWorkflow = "ar_collections" | "bank_recon" | "fpa_trend" | "treasury" | "reporting"

export interface User {
  id: string
  email: string
  full_name: string
  role: UserRole
  last_login_at: string | null
  areas: Area[]
  /** Service POD workflows they work in (every one for a Finance Admin) */
  pod_workflows: PodWorkflow[]
}

export const authApi = {
  login: (values: LoginFormValues) =>
    apiRequest<User>("/auth/login", { method: "POST", json: values, skipAuthRefresh: true }),

  logout: () => apiRequest<void>("/auth/logout", { method: "POST", skipAuthRefresh: true }),

  changePassword: (body: { current_password: string; new_password: string }) =>
    apiRequest<void>("/auth/me/password", { method: "POST", json: body }),

  /** Forgot password: a Finance Admin is asked to set a new one */
  requestReset: (email: string) =>
    apiRequest<{ message: string }>("/auth/password-reset-requests", {
      method: "POST",
      json: { email },
      skipAuthRefresh: true,
    }),

  /** Current user, or null when not signed in */
  me: async (): Promise<User | null> => {
    try {
      return await apiRequest<User>("/auth/me")
    } catch (error) {
      if (error instanceof ApiError && error.status === 401) return null
      throw error
    }
  },
}
