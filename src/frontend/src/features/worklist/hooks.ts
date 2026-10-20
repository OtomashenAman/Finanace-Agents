import { useQuery } from "@tanstack/react-query"

import { worklistApi } from "./api"

/** Also drives the sidebar count, so it refreshes on its own and after any change */
export function useWorklist() {
  return useQuery({
    queryKey: ["worklist"],
    queryFn: worklistApi.get,
    meta: { dependsOn: ["runs", "data-sources", "users", "governance", "entities"] },
    refetchInterval: 60_000,
    refetchOnWindowFocus: true,
  })
}
