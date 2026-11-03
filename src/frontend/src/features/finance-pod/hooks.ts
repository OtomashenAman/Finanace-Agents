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

export function useOpenCase() {
  return useMutation({ mutationFn: financeApi.open, meta: { invalidates } })
}

export function useSources(workflow: string | null) {
  return useQuery({
    queryKey: [FINANCE_TAG, "sources", workflow],
    queryFn: () => financeApi.sources(workflow!),
    enabled: Boolean(workflow),
  })
}

/** Snapshots a case can be verified against or moved to (anyone working on the case). */
export function useCaseSources(caseId: string) {
  return useQuery({
    queryKey: [FINANCE_TAG, "case-sources", caseId],
    queryFn: () => financeApi.caseSources(caseId),
  })
}

export function useSourceCatalogue(snapshotId: string | null, workflow: string | null) {
  return useQuery({
    queryKey: [FINANCE_TAG, "source-catalogue", snapshotId, workflow],
    queryFn: () => financeApi.sourceCatalogue(snapshotId!, workflow!),
    enabled: Boolean(snapshotId && workflow),
    staleTime: 5 * 60_000,
  })
}

export function useCaseCatalogue(caseId: string | undefined) {
  return useQuery({
    queryKey: [FINANCE_TAG, "catalogue", caseId],
    queryFn: () => financeApi.caseCatalogue(caseId!),
    enabled: Boolean(caseId),
    staleTime: 5 * 60_000,
  })
}

export function useUpload() {
  return useMutation({ mutationFn: financeApi.upload, meta: { invalidates } })
}

export function useSendMessage() {
  return useMutation({ mutationFn: financeApi.sendMessage, meta: { invalidates } })
}

export function useTaskAction() {
  return useMutation({ mutationFn: financeApi.taskAction, meta: { invalidates } })
}

export function useSanctions(enabled: boolean) {
  return useQuery({ queryKey: [FINANCE_TAG, "sanctions"], queryFn: financeApi.sanctions, enabled })
}

export function useRefreshSanctions() {
  return useMutation({ mutationFn: financeApi.refreshSanctions, meta: { invalidates } })
}

export function useIntake() {
  return useMutation({ mutationFn: financeApi.intake, meta: { invalidates } })
}
