import { hashKey, useMutation, useQuery, useQueryClient } from "@tanstack/react-query"

import { AUTH_ME_KEY } from "@/lib/query-client"
import { rememberSlot, startNewSlot } from "@/lib/session-slot"

import { authApi } from "./api"

export const authKeys = {
  me: AUTH_ME_KEY,
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
    onSuccess: (user) => {
      rememberSlot()
      queryClient.setQueryData(authKeys.me, user)
    },
  })
}

/** Drop all cached data but keep the "me" query (set to null) so mounted route guards see the
 *  change; queryClient.clear() would detach them from the cache. */
function useSignedOutCache() {
  const queryClient = useQueryClient()
  return () => {
    queryClient.setQueryData(authKeys.me, null)
    queryClient.removeQueries({ predicate: (query) => query.queryHash !== hashKey(authKeys.me) })
  }
}

export function useLogout() {
  const signedOut = useSignedOutCache()
  return useMutation({
    mutationFn: authApi.logout,
    // Even if the request fails, treat the user as signed out
    onSettled: signedOut,
  })
}

/** Sign in with another account in this tab only; other tabs stay signed in as they are. */
export function useSwitchAccount() {
  const signedOut = useSignedOutCache()
  return () => {
    startNewSlot()
    signedOut()
  }
}
