import { ApiError, apiRequest } from "@/lib/api"

import type { LoginFormValues } from "./schema"

export type UserRole = "finance_admin" | "preparer" | "reviewer"

export interface User {
  id: string
  email: string
  full_name: string
  role: UserRole
  last_login_at: string | null
}

export const authApi = {
  login: (values: LoginFormValues) =>
    apiRequest<User>("/auth/login", { method: "POST", json: values, skipAuthRefresh: true }),

  logout: () => apiRequest<void>("/auth/logout", { method: "POST", skipAuthRefresh: true }),

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
