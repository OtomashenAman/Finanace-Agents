import { useMutation, useQuery } from "@tanstack/react-query"

import { dataSourcesApi } from "./api"

/** Cache tag for everything derived from data sources (the admin overview dependsOn it) */
export const DATA_SOURCES_TAG = "data-sources"

export const dataSourceKeys = {
  list: () => [DATA_SOURCES_TAG, "list"] as const,
  recordTypes: () => [DATA_SOURCES_TAG, "record-types"] as const,
  quickbooksStatus: () => [DATA_SOURCES_TAG, "quickbooks-status"] as const,
  records: (id: string, type: string, search: string) => [DATA_SOURCES_TAG, "records", id, type, search] as const,
  integration: () => [DATA_SOURCES_TAG, "integration"] as const,
  all: () => [DATA_SOURCES_TAG, "all"] as const,
}

const invalidates = [DATA_SOURCES_TAG] as const

export function useDataSources() {
  return useQuery({ queryKey: dataSourceKeys.list(), queryFn: dataSourcesApi.list })
}

export function useRecordTypes() {
  return useQuery({ queryKey: dataSourceKeys.recordTypes(), queryFn: dataSourcesApi.recordTypes, staleTime: Infinity })
}

export function useQuickBooksStatus() {
  return useQuery({ queryKey: dataSourceKeys.quickbooksStatus(), queryFn: dataSourcesApi.quickbooksStatus })
}

export function useSourceRecords(id: string | null, type: string, search: string) {
  return useQuery({
    queryKey: dataSourceKeys.records(id ?? "", type, search),
    queryFn: () => dataSourcesApi.records(id!, type, search),
    enabled: id !== null,
  })
}

/** Starts the Intuit round trip: the browser leaves the app and comes back to /data-sources */
export function useAuthorizeQuickBooks() {
  return useMutation({
    mutationFn: dataSourcesApi.authorize,
    onSuccess: ({ url }) => window.location.assign(url),
  })
}

export function useSyncSource() {
  return useMutation({ mutationFn: dataSourcesApi.sync, meta: { invalidates } })
}

export function useRenameSource() {
  return useMutation({ mutationFn: dataSourcesApi.rename, meta: { invalidates } })
}

export function useDeleteSource() {
  return useMutation({ mutationFn: dataSourcesApi.remove, meta: { invalidates: [...invalidates, "runs"] } })
}

export function usePreviewUpload() {
  return useMutation({ mutationFn: dataSourcesApi.preview })
}

export function useUpload() {
  return useMutation({ mutationFn: dataSourcesApi.upload, meta: { invalidates } })
}

export function useIntegration() {
  return useQuery({ queryKey: dataSourceKeys.integration(), queryFn: dataSourcesApi.integration })
}

export function useSetIntegration() {
  return useMutation({ mutationFn: dataSourcesApi.setIntegration, meta: { invalidates } })
}

export function useAllSources() {
  return useQuery({ queryKey: dataSourceKeys.all(), queryFn: dataSourcesApi.allSources })
}
