import { useMutation, useQuery } from "@tanstack/react-query"

import { entitiesApi } from "./api"

/** Cache tag: runs, users and the overview show entity names */
export const ENTITIES_TAG = "entities"

export function useEntities() {
  return useQuery({ queryKey: [ENTITIES_TAG, "list"], queryFn: entitiesApi.list, staleTime: 5 * 60_000 })
}

const invalidates = [ENTITIES_TAG, "users", "runs", "overview"] as const

export function useCreateEntity() {
  return useMutation({ mutationFn: entitiesApi.create, meta: { invalidates } })
}

export function useUpdateEntity() {
  return useMutation({ mutationFn: entitiesApi.update, meta: { invalidates } })
}
