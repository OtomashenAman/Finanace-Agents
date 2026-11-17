import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"

import { esignApi, type Stage } from "./api"

const TAG = "esign"

export const esignKeys = {
  setup: () => [TAG, "setup"] as const,
  templates: () => [TAG, "templates"] as const,
  documents: (stage: Stage | null, search: string) => [TAG, "documents", stage, search] as const,
  document: (id: string) => [TAG, "document", id] as const,
  report: () => [TAG, "report"] as const,
}

function useInvalidate() {
  const client = useQueryClient()
  return () => client.invalidateQueries({ queryKey: [TAG] })
}

export function useEsignSetup() {
  return useQuery({ queryKey: esignKeys.setup(), queryFn: esignApi.setup, staleTime: Infinity })
}

export function useTemplates() {
  return useQuery({ queryKey: esignKeys.templates(), queryFn: esignApi.templates })
}

export function useDocuments(stage: Stage | null, search: string) {
  return useQuery({
    queryKey: esignKeys.documents(stage, search),
    queryFn: () => esignApi.documents(stage, search),
    // Statuses arrive by webhook: check back while something is out for signature
    refetchInterval: (query) =>
      query.state.data?.items.some((d) => d.send_pending || d.stage === "sent" || d.stage === "viewed")
        ? 20_000
        : false,
  })
}

export function useDocument(id: string | null) {
  return useQuery({
    queryKey: esignKeys.document(id ?? ""),
    queryFn: () => esignApi.document(id!),
    enabled: id !== null,
  })
}

export function useReport() {
  return useQuery({ queryKey: esignKeys.report(), queryFn: esignApi.report, refetchInterval: 60_000 })
}

export function useUploadTemplate() {
  const invalidate = useInvalidate()
  return useMutation({ mutationFn: esignApi.uploadTemplate, onSuccess: invalidate })
}

export function useDeleteTemplate() {
  const invalidate = useInvalidate()
  return useMutation({ mutationFn: esignApi.deleteTemplate, onSuccess: invalidate })
}

export function useSendDocument() {
  const invalidate = useInvalidate()
  return useMutation({ mutationFn: esignApi.send, onSuccess: invalidate })
}

export function useRefreshDocument() {
  const invalidate = useInvalidate()
  return useMutation({ mutationFn: esignApi.refresh, onSuccess: invalidate })
}

/** My PandaDoc signing session, once everyone else has signed */
export function useCountersign() {
  return useMutation({ mutationFn: esignApi.countersign })
}

/** Documents waiting for my countersignature (sidebar badge) */
export function useAwaitingMe() {
  return useQuery({ queryKey: esignKeys.report(), queryFn: esignApi.report, refetchInterval: 60_000 }).data
    ?.awaiting_you
}

export function useRetrySend() {
  const invalidate = useInvalidate()
  return useMutation({ mutationFn: esignApi.retrySend, onSuccess: invalidate })
}
