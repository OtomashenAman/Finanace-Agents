import { useMutation, useQuery } from "@tanstack/react-query"

import { jobsApi, monitoringApi } from "./api"

export function useAiMonitoring(days: number) {
  return useQuery({
    queryKey: ["ai-monitoring", days],
    queryFn: () => monitoringApi.summary(days),
    // New calls happen whenever someone analyzes a run
    meta: { dependsOn: ["runs"] },
    refetchInterval: 60_000,
  })
}

export function useQueue() {
  return useQuery({
    queryKey: ["jobs"],
    queryFn: jobsApi.summary,
    meta: { dependsOn: ["runs"] },
    refetchInterval: 10_000,
  })
}

export function useRetryJob() {
  return useMutation({ mutationFn: jobsApi.retry, meta: { invalidates: ["jobs", "runs"] } })
}
