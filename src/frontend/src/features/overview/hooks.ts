import { keepPreviousData, useQuery } from "@tanstack/react-query"

import { overviewApi, type OverviewFilters } from "./api"

export const overviewKeys = {
  summary: (filters: OverviewFilters) => ["overview", "summary", filters] as const,
}

export function useOverviewSummary(filters: OverviewFilters = {}) {
  return useQuery({
    queryKey: overviewKeys.summary(filters),
    queryFn: () => overviewApi.summary(filters),
    // Keep showing the last numbers while a new period/entity loads
    placeholderData: keepPreviousData,
    // Derived from the catalog, runs and data sources: refetched when those change
    meta: { dependsOn: ["agents", "runs", "data-sources", "entities"] },
    // Other users' changes show up without a manual refresh
    refetchInterval: 60_000,
    refetchOnWindowFocus: true,
  })
}
