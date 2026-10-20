import { apiRequest } from "@/lib/api"

export type SourceKind = "quickbooks" | "upload"
export type SourceStatus = "pending_auth" | "connected" | "needs_reauth" | "error" | "ready"
export type RecordType = "vendor" | "bill" | "purchase_order" | "account"
export type IntegrationEnvironment = "sandbox" | "production"

export interface DataSource {
  id: string
  kind: SourceKind
  name: string
  status: SourceStatus
  external_id: string | null
  last_synced_at: string | null
  last_error: string | null
  record_counts: Partial<Record<RecordType, number>>
  filename: string | null
  created_at: string
  updated_at: string
}

export interface AdminDataSource extends DataSource {
  owner: { id: string; full_name: string; email: string }
}

export interface RecordTypeInfo {
  type: RecordType
  label: string
  fields: { name: string; required: boolean }[]
}

export type ColumnMapping = Record<string, string | null>

export interface UploadPreview {
  record_type: RecordType
  headers: string[]
  mapping: ColumnMapping
  sample_rows: string[][]
  row_count: number
  valid_count: number
  error_count: number
  errors: string[]
}

export interface UploadResult {
  source: DataSource
  imported: number
  skipped: number
}

export interface FinanceRecord {
  external_id: string
  record_type: RecordType
  reference: string
  counterparty: string | null
  amount: string | null
  txn_date: string | null
  data: Record<string, unknown>
}

export interface QuickBooksStatus {
  configured: boolean
  environment: IntegrationEnvironment | null
}

export interface IntegrationApp {
  provider: "quickbooks"
  configured: boolean
  client_id: string | null
  has_client_secret: boolean
  environment: IntegrationEnvironment
  redirect_uri: string
  updated_at: string | null
}

export interface IntegrationAppUpdate {
  client_id: string
  client_secret?: string
  environment: IntegrationEnvironment
}

export interface UploadRequest {
  file: File
  recordType: RecordType
  mapping?: ColumnMapping
  name?: string
  skipInvalid?: boolean
}

const source = (id: string) => `/data-sources/${encodeURIComponent(id)}`

function uploadForm({ file, recordType, mapping, name, skipInvalid }: UploadRequest): FormData {
  const form = new FormData()
  form.append("file", file)
  form.append("record_type", recordType)
  if (mapping) form.append("mapping", JSON.stringify(mapping))
  if (name) form.append("name", name)
  if (skipInvalid) form.append("skip_invalid", "true")
  return form
}

export const dataSourcesApi = {
  list: () => apiRequest<DataSource[]>("/data-sources"),
  recordTypes: () => apiRequest<RecordTypeInfo[]>("/data-sources/record-types"),
  quickbooksStatus: () => apiRequest<QuickBooksStatus>("/data-sources/quickbooks/status"),
  /** Intuit sign-in URL; pass sourceId to re-authorize an existing connection */
  authorize: (sourceId?: string) =>
    apiRequest<{ url: string }>("/data-sources/quickbooks/authorize", {
      method: "POST",
      json: { source_id: sourceId ?? null },
    }),
  sync: (id: string) => apiRequest<DataSource>(`${source(id)}/sync`, { method: "POST" }),
  rename: ({ id, name }: { id: string; name: string }) =>
    apiRequest<DataSource>(source(id), { method: "PATCH", json: { name } }),
  remove: (id: string) => apiRequest<void>(source(id), { method: "DELETE" }),
  records: (id: string, type: string, search: string) =>
    apiRequest<FinanceRecord[]>(
      `${source(id)}/records?${new URLSearchParams({ type, ...(search ? { search } : {}) })}`,
    ),
  preview: (req: UploadRequest) =>
    apiRequest<UploadPreview>("/data-sources/uploads/preview", { method: "POST", form: uploadForm(req) }),
  upload: (req: UploadRequest) =>
    apiRequest<UploadResult>("/data-sources/uploads", { method: "POST", form: uploadForm(req) }),

  // Finance Admin
  integration: () => apiRequest<IntegrationApp>("/admin/integrations/quickbooks"),
  setIntegration: (body: IntegrationAppUpdate) =>
    apiRequest<IntegrationApp>("/admin/integrations/quickbooks", { method: "PUT", json: body }),
  allSources: () => apiRequest<AdminDataSource[]>("/admin/data-sources"),
}
