import { useQuery } from "@tanstack/react-query"

import { approvalsApi } from "./api"

export const approvalKeys = {
  list: (decided: boolean) => ["approvals", decided ? "decided" : "pending"] as const,
}

export function useApprovals(decided: boolean) {
  return useQuery({
    queryKey: approvalKeys.list(decided),
    queryFn: () => approvalsApi.list(decided),
    // A submit or review anywhere changes the queue
    meta: { dependsOn: ["runs"] },
    refetchInterval: 60_000,
    refetchOnWindowFocus: true,
  })
}
