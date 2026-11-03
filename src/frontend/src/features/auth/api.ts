import { ApiError, apiRequest } from "@/lib/api"

import type { LoginFormValues } from "./schema"

export type UserRole = "finance_admin" | "user"

export interface User {
  id: string
  email: string
  full_name: string
  role: UserRole
  last_login_at: string | null
}

/** The signed-in user of this tab (from /auth/me) */
export interface Me extends User {
  /** This tab is a Finance Admin testing as this user */
  acted_by: { id: string; full_name: string; email: string } | null
  /** A Finance Admin who may open a tab as another user here (dev and demo) */
  can_act_as: boolean
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

  /** A Finance Admin opens `slot` (a new tab's) as another user, to do their step */
  actAs: (userId: string, slot: string) =>
    apiRequest<User>("/auth/act-as", { method: "POST", json: { user_id: userId, slot } }),

  /** Current user, or null when not signed in */
  me: async (): Promise<Me | null> => {
    try {
      return await apiRequest<Me>("/auth/me")
    } catch (error) {
      if (error instanceof ApiError && error.status === 401) return null
      throw error
    }
  },
}
