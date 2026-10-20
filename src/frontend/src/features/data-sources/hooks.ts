import { useMutation, useQuery } from "@tanstack/react-query"

import { dataSourcesApi, type AuthorizeResponse, type QuickBooksApp } from "./api"

/** Cache tag for everything derived from data sources (the admin overview dependsOn it) */
export const DATA_SOURCES_TAG = "data-sources"

export const dataSourceKeys = {
  list: () => [DATA_SOURCES_TAG, "list"] as const,
  recordTypes: () => [DATA_SOURCES_TAG, "record-types"] as const,
  redirectUri: () => [DATA_SOURCES_TAG, "redirect-uri"] as const,
  records: (id: string, type: string, search: string) => [DATA_SOURCES_TAG, "records", id, type, search] as const,
  all: () => [DATA_SOURCES_TAG, "all"] as const,
}

const invalidates = [DATA_SOURCES_TAG] as const

export function useDataSources() {
  return useQuery({ queryKey: dataSourceKeys.list(), queryFn: dataSourcesApi.list })
}

export function useRecordTypes() {
  return useQuery({ queryKey: dataSourceKeys.recordTypes(), queryFn: dataSourcesApi.recordTypes, staleTime: Infinity })
}

export function useRedirectUri() {
  return useQuery({ queryKey: dataSourceKeys.redirectUri(), queryFn: dataSourcesApi.redirectUri, staleTime: Infinity })
}

export function useSourceRecords(id: string | null, type: string, search: string) {
  return useQuery({
    queryKey: dataSourceKeys.records(id ?? "", type, search),
    queryFn: () => dataSourcesApi.records(id!, type, search),
    enabled: id !== null,
  })
}

/** Send the browser to Intuit. The promise never settles: the mutation stays pending until the
 *  page has navigated away, so Connect / Re-authorize can't be clicked twice meanwhile. */
function goToIntuit({ url }: AuthorizeResponse): Promise<never> {
  window.location.assign(url)
  return new Promise<never>(() => {})
}

export function useConnectQuickBooks() {
  return useMutation({ mutationFn: (app: QuickBooksApp) => dataSourcesApi.connect(app).then(goToIntuit) })
}

export function useAuthorizeQuickBooks() {
  return useMutation({ mutationFn: (id: string) => dataSourcesApi.authorize(id).then(goToIntuit) })
}

export function useUpdateApp() {
  return useMutation({ mutationFn: dataSourcesApi.updateApp, meta: { invalidates } })
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

export function useAllSources() {
  return useQuery({ queryKey: dataSourceKeys.all(), queryFn: dataSourcesApi.allSources })
}
