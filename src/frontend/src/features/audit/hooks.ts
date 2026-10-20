import { useInfiniteQuery, useMutation, useQuery } from "@tanstack/react-query"

import { auditApi, type AuditFilters } from "./api"

// Every feature writes audit events: refresh whenever anything changes
const EVERYTHING = ["runs", "agents", "users", "data-sources"] as const

export const auditKeys = {
  list: (filters: AuditFilters) => ["audit", "list", filters] as const,
  timeline: (agentKey: string, runId: string) => ["audit", "timeline", agentKey, runId] as const,
}

export function useAuditEvents(filters: AuditFilters) {
  return useInfiniteQuery({
    queryKey: auditKeys.list(filters),
    queryFn: ({ pageParam }) => auditApi.list(filters, pageParam),
    initialPageParam: null as string | null,
    getNextPageParam: (page) => page.next_cursor,
    meta: { dependsOn: EVERYTHING },
  })
}

export function useRunTimeline(agentKey: string, runId: string) {
  return useQuery({
    queryKey: auditKeys.timeline(agentKey, runId),
    queryFn: () => auditApi.timeline(agentKey, runId),
    meta: { dependsOn: ["runs"] },
  })
}

export function useExportAudit() {
  return useMutation({ mutationFn: auditApi.exportCsv, meta: { invalidates: ["audit"] } })
}

export function useAuditIntegrity(enabled: boolean) {
  return useQuery({ queryKey: ["audit", "integrity"], queryFn: auditApi.integrity, enabled })
}
