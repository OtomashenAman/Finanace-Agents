import { useQuery } from "@tanstack/react-query"

import { monitoringApi } from "./api"

export function useAiMonitoring(days: number) {
  return useQuery({
    queryKey: ["ai-monitoring", days],
    queryFn: () => monitoringApi.summary(days),
    // New calls happen whenever someone analyzes a run
    meta: { dependsOn: ["runs"] },
    refetchInterval: 60_000,
  })
}
