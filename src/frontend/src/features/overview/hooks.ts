import { useQuery } from "@tanstack/react-query"

import { overviewApi } from "./api"

export const overviewKeys = {
  summary: (period?: string) => ["overview", "summary", period ?? "current"] as const,
}

export function useOverviewSummary(period?: string) {
  return useQuery({
    queryKey: overviewKeys.summary(period),
    queryFn: () => overviewApi.summary(period),
    // Derived from the catalog (and later runs): refetched when those change
    meta: { dependsOn: ["agents", "runs"] },
    // Other users' changes show up without a manual refresh
    refetchInterval: 60_000,
    refetchOnWindowFocus: true,
  })
}
