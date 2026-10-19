import type { AgentCapacity } from "@/features/agent-catalog/api"
import type { UserRole } from "@/features/auth/api"
import { apiRequest } from "@/lib/api"

export interface Assignment {
  agent_key: string
  capacity: AgentCapacity
}

export interface ManagedUser {
  id: string
  email: string
  full_name: string
  role: UserRole
  is_active: boolean
  is_locked: boolean
  last_login_at: string | null
  created_at: string
  assignments: (Assignment & { agent_name: string })[]
}

export interface UserCreate {
  email: string
  full_name: string
  role: UserRole
  password: string
  assignments: Assignment[]
}

export interface UserUpdate {
  full_name?: string
  role?: UserRole
  is_active?: boolean
}

const user = (id: string) => `/users/${encodeURIComponent(id)}`

export const usersApi = {
  list: (search: string) =>
    apiRequest<ManagedUser[]>(search ? `/users?search=${encodeURIComponent(search)}` : "/users"),
  create: (body: UserCreate) => apiRequest<ManagedUser>("/users", { method: "POST", json: body }),
  update: ({ id, ...body }: UserUpdate & { id: string }) =>
    apiRequest<ManagedUser>(user(id), { method: "PATCH", json: body }),
  resetPassword: ({ id, password }: { id: string; password: string }) =>
    apiRequest<ManagedUser>(`${user(id)}/password`, { method: "POST", json: { password } }),
  setAssignments: ({ id, assignments }: { id: string; assignments: Assignment[] }) =>
    apiRequest<ManagedUser>(`${user(id)}/assignments`, { method: "PUT", json: { assignments } }),
  remove: (id: string) => apiRequest<void>(user(id), { method: "DELETE" }),
}
