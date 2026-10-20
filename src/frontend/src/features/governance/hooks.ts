import { useMutation, useQuery } from "@tanstack/react-query"

import { governanceApi } from "./api"

/** Cache tag: runs show the policy version and approvals they got */
export const GOVERNANCE_TAG = "governance"

const invalidates = [GOVERNANCE_TAG, "runs", "worklist"] as const

export function useOrgSettings() {
  return useQuery({ queryKey: [GOVERNANCE_TAG, "settings"], queryFn: governanceApi.settings })
}

export function useSetOrgSettings() {
  return useMutation({ mutationFn: governanceApi.setSettings, meta: { invalidates } })
}

export function usePolicies() {
  return useQuery({ queryKey: [GOVERNANCE_TAG, "policies"], queryFn: governanceApi.policies })
}

export function usePolicyHistory(key: string, enabled: boolean) {
  return useQuery({ queryKey: [GOVERNANCE_TAG, "history", key], queryFn: () => governanceApi.history(key), enabled })
}

export function useSavePolicy() {
  return useMutation({ mutationFn: governanceApi.savePolicy, meta: { invalidates } })
}

export function useMatrices() {
  return useQuery({ queryKey: [GOVERNANCE_TAG, "matrices"], queryFn: governanceApi.matrices })
}

export function useSaveMatrix() {
  return useMutation({ mutationFn: governanceApi.saveMatrix, meta: { invalidates } })
}
