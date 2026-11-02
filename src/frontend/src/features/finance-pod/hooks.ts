import { useMutation, useQuery } from "@tanstack/react-query"

import { useCurrentUser } from "@/features/auth/hooks"

import { financeApi } from "./api"

/** Every Finance POD query starts with this key; any Finance POD change refreshes them all
 *  (a step done on one case moves the queue, the dashboard and the case together). */
export const FINANCE_TAG = "finance"
const invalidates = [FINANCE_TAG] as const

/** The viewer's Finance POD access. A 403 (no capacity) is an answer, not an error. */
export function useFinanceMe() {
  const { data: user } = useCurrentUser()
  return useQuery({
    queryKey: [FINANCE_TAG, "me", user?.id],
    queryFn: financeApi.me,
    enabled: Boolean(user),
    staleTime: 5 * 60_000,
    retry: false,
  })
}

export function useFinanceDashboard() {
  return useQuery({ queryKey: [FINANCE_TAG, "dashboard"], queryFn: financeApi.dashboard })
}

export function useFinanceWorkflows() {
  return useQuery({ queryKey: [FINANCE_TAG, "workflows"], queryFn: financeApi.workflows, staleTime: 60_000 })
}

export function useFinanceCases(filters: { workflow?: string | null; status?: string | null }) {
  return useQuery({ queryKey: [FINANCE_TAG, "cases", filters], queryFn: () => financeApi.cases(filters) })
}

export function useFinanceCase(id: string | undefined) {
  return useQuery({
    queryKey: [FINANCE_TAG, "case", id],
    queryFn: () => financeApi.case(id!),
    enabled: Boolean(id),
  })
}

export function useCaseAction() {
  return useMutation({ mutationFn: financeApi.act, meta: { invalidates } })
}

export function useCapacityCatalog() {
  return useQuery({ queryKey: [FINANCE_TAG, "catalog"], queryFn: financeApi.catalog, staleTime: 60 * 60_000 })
}

export function useAssignments() {
  return useQuery({ queryKey: [FINANCE_TAG, "assignments"], queryFn: financeApi.assignments })
}

export function useGrant() {
  return useMutation({ mutationFn: financeApi.grant, meta: { invalidates } })
}

export function useRevoke() {
  return useMutation({ mutationFn: financeApi.revoke, meta: { invalidates } })
}
