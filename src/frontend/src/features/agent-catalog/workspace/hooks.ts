import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"

import { runsApi, type FieldValue, type ReviewDecision, type RunDetail } from "./api"

/** Cache tag for everything derived from runs (the overview dependsOn it) */
export const RUNS_TAG = "runs"

export const runKeys = {
  form: (key: string) => [RUNS_TAG, "form", key] as const,
  list: (key: string) => [RUNS_TAG, "list", key] as const,
  detail: (key: string, id: string) => [RUNS_TAG, "detail", key, id] as const,
}

export function useFormSpec(key: string, enabled = true) {
  return useQuery({ queryKey: runKeys.form(key), queryFn: () => runsApi.form(key), enabled, staleTime: Infinity })
}

export function useRuns(key: string, enabled = true) {
  return useQuery({ queryKey: runKeys.list(key), queryFn: () => runsApi.list(key), enabled })
}

export function useRun(key: string, id: string) {
  return useQuery({ queryKey: runKeys.detail(key, id), queryFn: () => runsApi.get(key, id) })
}

/** Every run mutation returns the fresh run: show it immediately, then refresh derived data. */
function useRunMutation<V>(key: string, fn: (vars: V) => Promise<RunDetail>) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: fn,
    onSuccess: (run) => queryClient.setQueryData(runKeys.detail(key, run.id), run),
    meta: { invalidates: [RUNS_TAG] },
  })
}

export function useCreateRun(key: string) {
  return useRunMutation<void>(key, () => runsApi.create(key))
}

export function useSaveInput(key: string, id: string) {
  return useRunMutation<Record<string, FieldValue>>(key, (values) => runsApi.saveInput(key, id, values))
}

export function useAnalyzeRun(key: string, id: string) {
  return useRunMutation<void>(key, () => runsApi.analyze(key, id))
}

export function useSubmitRun(key: string, id: string) {
  return useRunMutation<void>(key, () => runsApi.submit(key, id))
}

export function useReviewRun(key: string, id: string) {
  return useRunMutation<{ decision: ReviewDecision; comment: string }>(key, ({ decision, comment }) =>
    runsApi.review(key, id, decision, comment),
  )
}

export function useUploadDocument(key: string, id: string) {
  return useRunMutation<File>(key, (file) => runsApi.uploadDocument(key, id, file))
}

export function useRemoveDocument(key: string, id: string) {
  return useRunMutation<string>(key, (documentId) => runsApi.removeDocument(key, id, documentId))
}

export function useLinkSource(key: string, id: string) {
  return useRunMutation<{ sourceId: string; recordId: string }>(key, ({ sourceId, recordId }) =>
    runsApi.linkSource(key, id, sourceId, recordId),
  )
}

export function useUnlinkSource(key: string, id: string) {
  return useRunMutation<void>(key, () => runsApi.unlinkSource(key, id))
}

export function useDeleteRun(key: string, id: string) {
  return useMutation({ mutationFn: () => runsApi.remove(key, id), meta: { invalidates: [RUNS_TAG] } })
}
