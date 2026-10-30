import { useMutation, useQuery } from "@tanstack/react-query"

import { podApi, type Collection, type MessageStatus, type TaskStatus } from "./api"

/** Every Service POD query starts with this key, and every POD change refreshes them all:
 *  a reply, an approval or a posting moves cases, the inbox and the task queue together. */
export const POD_TAG = "pod"
const invalidates = [POD_TAG] as const

export function useWorkflows() {
  return useQuery({ queryKey: [POD_TAG, "workflows"], queryFn: podApi.workflows, staleTime: 60_000 })
}

export function useEmailStatus(enabled = true) {
  return useQuery({ queryKey: [POD_TAG, "email-status"], queryFn: podApi.emailStatus, enabled, staleTime: 60_000 })
}

export function useSnapshots(includeArchived = false) {
  return useQuery({ queryKey: [POD_TAG, "snapshots", includeArchived], queryFn: () => podApi.snapshots(includeArchived) })
}

export function useSnapshotRows(id: string | null, collection: Collection | null) {
  return useQuery({
    queryKey: [POD_TAG, "snapshot-rows", id, collection],
    queryFn: () => podApi.snapshotRows(id!, collection!),
    enabled: Boolean(id && collection),
  })
}

export function useCases(filters: { workflow?: string | null; status?: string | null }) {
  return useQuery({ queryKey: [POD_TAG, "cases", filters], queryFn: () => podApi.cases(filters) })
}

export function useCase(id: string | undefined) {
  return useQuery({ queryKey: [POD_TAG, "case", id], queryFn: () => podApi.case(id!), enabled: Boolean(id) })
}

export function useReviewQueue() {
  return useQuery({ queryKey: [POD_TAG, "review-queue"], queryFn: podApi.reviewQueue })
}

export function useMessages(status?: MessageStatus | null) {
  return useQuery({ queryKey: [POD_TAG, "messages", status ?? null], queryFn: () => podApi.messages(status) })
}

export function useTasks(status?: TaskStatus | null) {
  return useQuery({ queryKey: [POD_TAG, "tasks", status ?? null], queryFn: () => podApi.tasks(status) })
}

export function useArPortfolio() {
  return useQuery({ queryKey: [POD_TAG, "ar-portfolio"], queryFn: podApi.arPortfolio })
}

export function useBankWorklist() {
  return useQuery({ queryKey: [POD_TAG, "bank-worklist"], queryFn: podApi.bankWorklist })
}

function usePodMutation<TArgs, TResult>(fn: (args: TArgs) => Promise<TResult>) {
  return useMutation({ mutationFn: fn, meta: { invalidates } })
}

export const useImportJson = () => usePodMutation(podApi.importJson)
export const useImportQuickBooks = () => usePodMutation(podApi.importQuickBooks)
export const useImportBankStatement = () => usePodMutation(podApi.importBankStatement)
export const useCreateCase = () => usePodMutation(podApi.createCase)
export const useCaseAction = () => usePodMutation(podApi.caseAction)
export const useCreateDraft = () => usePodMutation(podApi.createDraft)
export const useUpdateMessage = () => usePodMutation(podApi.updateMessage)
export const useSendMessage = () => usePodMutation(podApi.sendMessage)
export const useImportQbxml = () => usePodMutation(podApi.importQbxml)
export const useArchiveSnapshot = () => usePodMutation(podApi.archiveSnapshot)
export const useRestoreSnapshot = () => usePodMutation(podApi.restoreSnapshot)
export const useDeleteSnapshot = () => usePodMutation(podApi.deleteSnapshot)
/** A suggested draft: nothing is saved, so nothing to refresh */
export const useCompose = () => useMutation({ mutationFn: podApi.compose })
export const useReconcile = () => usePodMutation(podApi.reconcile)
export const useImportReply = () => usePodMutation(podApi.importReply)
export const useUploadArtifact = () => usePodMutation(podApi.uploadArtifact)
export const useDecideArtifact = () => usePodMutation(podApi.decideArtifact)
export const useProposeTask = () => usePodMutation(podApi.proposeTask)
export const useTaskAction = () => usePodMutation(podApi.taskAction)
