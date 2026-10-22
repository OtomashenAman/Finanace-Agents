import { MutationCache, QueryCache, QueryClient, type Query } from "@tanstack/react-query"

import { ApiError } from "@/lib/api"

/**
 * Cross-feature cache invalidation without features importing each other:
 *  - a mutation declares what it changed:      meta: { invalidates: ["agents"] }
 *  - a query declares what it is derived from: meta: { dependsOn: ["agents"] }
 * Queries whose first key segment or dependsOn matches are refetched after the mutation.
 */
declare module "@tanstack/react-query" {
  interface Register {
    queryMeta: { dependsOn?: readonly string[] }
    mutationMeta: { invalidates?: readonly string[] }
  }
}

export const AUTH_ME_KEY = ["auth", "me"] as const

function isAffected(query: Query, tags: readonly string[]): boolean {
  const root = String(query.queryKey[0])
  return tags.includes(root) || (query.meta?.dependsOn ?? []).some((tag) => tags.includes(tag))
}

// A 401 that survived the refresh retry means the session is gone: sign the user out
function onApiError(error: unknown) {
  if (error instanceof ApiError && error.status === 401) {
    queryClient.setQueryData(AUTH_ME_KEY, null)
  }
}

export const queryClient: QueryClient = new QueryClient({
  queryCache: new QueryCache({ onError: onApiError }),
  mutationCache: new MutationCache({
    onError: onApiError,
    onSuccess: (_data, _variables, _onMutateResult, mutation) => {
      const tags = mutation.meta?.invalidates
      if (tags?.length) {
        void queryClient.invalidateQueries({ predicate: (query) => isAffected(query, tags) })
      }
    },
  }),
  defaultOptions: {
    queries: {
      refetchOnWindowFocus: false,
      // Retry only transient failures, never 4xx
      retry: (count, error) => !(error instanceof ApiError && error.status >= 400 && error.status < 500) && count < 2,
    },
  },
})
