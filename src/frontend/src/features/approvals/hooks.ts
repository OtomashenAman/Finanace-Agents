import { useQuery } from "@tanstack/react-query"

import { approvalsApi } from "./api"

export const approvalKeys = {
  list: (decided: boolean, entityId?: string | null) =>
    ["approvals", decided ? "decided" : "pending", entityId ?? "all"] as const,
}

export function useApprovals(decided: boolean, entityId?: string | null) {
  return useQuery({
    queryKey: approvalKeys.list(decided, entityId),
    queryFn: () => approvalsApi.list(decided, entityId),
    // A submit or review anywhere changes the queue
    meta: { dependsOn: ["runs", "entities"] },
    refetchInterval: 60_000,
    refetchOnWindowFocus: true,
  })
}
