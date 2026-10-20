import { useMutation, useQuery } from "@tanstack/react-query"

import { usersApi } from "./api"

/** Cache tag for the user list; "auth" refreshes the signed-in user if they edited themselves */
export const USERS_TAG = "users"

export const userKeys = {
  list: (search: string) => [USERS_TAG, "list", search] as const,
}

export function useUsers(search: string, enabled = true) {
  return useQuery({ queryKey: userKeys.list(search), queryFn: () => usersApi.list(search), enabled })
}

const invalidates = [USERS_TAG, "auth"] as const

export function useCreateUser() {
  return useMutation({ mutationFn: usersApi.create, meta: { invalidates } })
}

export function useUpdateUser() {
  return useMutation({ mutationFn: usersApi.update, meta: { invalidates } })
}

export function useResetPassword() {
  return useMutation({ mutationFn: usersApi.resetPassword, meta: { invalidates } })
}

export function useSetAssignments() {
  return useMutation({ mutationFn: usersApi.setAssignments, meta: { invalidates } })
}

export function useDeleteUser() {
  return useMutation({ mutationFn: usersApi.remove, meta: { invalidates } })
}
