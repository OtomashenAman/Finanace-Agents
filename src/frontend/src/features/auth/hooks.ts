import { hashKey, useMutation, useQuery, useQueryClient } from "@tanstack/react-query"

import { AUTH_ME_KEY } from "@/lib/query-client"
import { freshSlot, rememberSlot, startNewSlot } from "@/lib/session-slot"

import { authApi, type Me } from "./api"

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
      queryClient.setQueryData<Me>(authKeys.me, { ...user, acted_by: null, can_act_as: false })
      // /auth/me carries what the login response doesn't (an admin's act-as permission)
      void queryClient.invalidateQueries({ queryKey: authKeys.me })
    },
  })
}

export function useChangePassword() {
  return useMutation({ mutationFn: authApi.changePassword })
}

export function useRequestReset() {
  return useMutation({ mutationFn: authApi.requestReset })
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

/** A Finance Admin opens a new tab signed in as another user (testing a workflow), at
 *  `path`; this tab stays the admin's. The tab is opened first so no pop-up blocker stops it. */
export function useActAs() {
  return useMutation({
    mutationFn: async ({ userId, path }: { userId: string; path: string }) => {
      const tab = window.open("about:blank", "_blank")
      const slot = freshSlot()
      try {
        await authApi.actAs(userId, slot)
      } catch (error) {
        tab?.close()
        throw error
      }
      const url = `${path}#as=${slot}`
      if (tab) tab.location.href = url
      else window.location.assign(url)
    },
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
