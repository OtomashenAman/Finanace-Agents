import { apiRequest } from "@/lib/api"

export type SourceKind = "quickbooks" | "upload"
export type SourceStatus = "pending_auth" | "connected" | "needs_reauth" | "error" | "ready"
export type RecordType =
  | "vendor"
  | "bill"
  | "purchase_order"
  | "account"
  | "customer"
  | "invoice"
  | "payment"
  | "expense"
export type IntegrationEnvironment = "sandbox" | "production"

export interface DataSource {
  id: string
  kind: SourceKind
  name: string
  status: SourceStatus
  /** QuickBooks: the owner's own Intuit app (the secret is never returned) */
  client_id: string | null
  environment: IntegrationEnvironment | null
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

/** The user's own Intuit app (Intuit Developer portal → Keys & OAuth) */
export interface QuickBooksApp {
  client_id: string
  client_secret: string
  environment: IntegrationEnvironment
}

/** Omit client_secret to keep the stored one */
export type QuickBooksAppUpdate = Omit<QuickBooksApp, "client_secret"> & { client_secret?: string }

export interface AuthorizeResponse {
  source: DataSource
  url: string
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
  redirectUri: () => apiRequest<{ redirect_uri: string }>("/data-sources/quickbooks/redirect-uri"),
  /** Connect a company with the user's own Intuit app; returns the Intuit sign-in URL */
  connect: (app: QuickBooksApp) =>
    apiRequest<AuthorizeResponse>("/data-sources/quickbooks", { method: "POST", json: app }),
  /** Re-authorize an existing connection */
  authorize: (id: string) => apiRequest<AuthorizeResponse>(`${source(id)}/authorize`, { method: "POST" }),
  updateApp: ({ id, ...app }: QuickBooksAppUpdate & { id: string }) =>
    apiRequest<DataSource>(`${source(id)}/app`, { method: "PUT", json: app }),
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
  allSources: () => apiRequest<AdminDataSource[]>("/admin/data-sources"),
}
