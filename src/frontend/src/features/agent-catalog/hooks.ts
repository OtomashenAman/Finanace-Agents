import { useMutation, useQuery } from "@tanstack/react-query"

import { agentCatalogApi } from "./api"

/** Cache tag for everything derived from the catalog (see lib/query-client.ts) */
export const AGENTS_TAG = "agents"

export const agentKeys = {
  all: [AGENTS_TAG] as const,
  list: () => [AGENTS_TAG, "list"] as const,
  detail: (key: string) => [AGENTS_TAG, "detail", key] as const,
}

export function useAgents() {
  return useQuery({ queryKey: agentKeys.list(), queryFn: agentCatalogApi.list })
}

export function useAgent(key: string) {
  return useQuery({ queryKey: agentKeys.detail(key), queryFn: () => agentCatalogApi.get(key) })
}

export function useSetAgentActive() {
  return useMutation({
    mutationFn: agentCatalogApi.setActive,
    // Refreshes the catalog and every query that dependsOn "agents" (e.g. the overview)
    meta: { invalidates: [AGENTS_TAG] },
  })
}
