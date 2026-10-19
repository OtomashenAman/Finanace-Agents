import { hashKey, useMutation, useQuery, useQueryClient } from "@tanstack/react-query"

import { authApi } from "./api"

export const authKeys = {
  me: ["auth", "me"] as const,
}

export function useCurrentUser() {
  return useQuery({
    queryKey: authKeys.me,
    queryFn: authApi.me,
    staleTime: 5 * 60_000,
  })
}

export function useLogin() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: authApi.login,
    onSuccess: (user) => queryClient.setQueryData(authKeys.me, user),
  })
}

export function useLogout() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: authApi.logout,
    // Even if the request fails, treat the user as signed out and drop all other cached data.
    // Keep the "me" query itself (set to null) so mounted route guards see the change;
    // queryClient.clear() would detach them from the cache.
    onSettled: () => {
      queryClient.setQueryData(authKeys.me, null)
      queryClient.removeQueries({ predicate: (query) => query.queryHash !== hashKey(authKeys.me) })
    },
  })
}
