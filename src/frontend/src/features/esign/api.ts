import { apiDownload, apiRequest } from "@/lib/api"

export type Stage = "preparing" | "sent" | "viewed" | "completed" | "declined" | "voided" | "failed"

/** A signature box: page (1-based), offsets from the page's top-left corner, size (points) */
export interface SignatureLayout {
  page: number
  x: number
  y: number
  width: number
  height: number
}

export interface EsignSetup {
  configured: boolean
  webhook_configured: boolean
  webhook_url: string
  max_bytes: number
  default_layout: SignatureLayout
}

/** A PandaDoc field tag found in the template, e.g. {textfield:signer1:company___} */
export interface FieldTag {
  type: string
  role: string
  id: string | null
  required: boolean
  /** Has an id and is text/date/checkbox: the sender fills it in when sending */
  prefillable: boolean
}

export interface EsignTemplate {
  id: string
  name: string
  description: string | null
  filename: string
  content_type: string
  size_bytes: number
  /** null: the file has PandaDoc field tags */
  signature_layout: SignatureLayout | null
  field_tags: FieldTag[]
  /** signer3 in a tag -> 3 */
  signers_needed: number
  created_at: string
  times_sent: number
}

export interface Recipient {
  email: string
  name: string
  role: string
  has_completed: boolean
  completed_at: string | null
  /** The sender, signing after everyone else */
  countersigner?: boolean
}

export interface EsignDocument {
  id: string
  name: string
  template_id: string | null
  template_name: string
  pandadoc_id: string | null
  status: string
  status_label: string
  stage: Stage
  send_pending: boolean
  subject: string | null
  recipients: Recipient[]
  /** The sender signs last */
  countersign: boolean
  /** Everyone else has signed: the sender's countersignature is due */
  your_turn: boolean
  error: string | null
  created_at: string
  sent_at: string | null
  viewed_at: string | null
  completed_at: string | null
  status_changed_at: string | null
}

export interface EsignEvent {
  event: string
  status: string | null
  recipient_email: string | null
  detail: string | null
  created_at: string
}

export interface EsignDocumentDetail extends EsignDocument {
  message: string | null
  field_values: Record<string, string | boolean>
  events: EsignEvent[]
}

export interface EsignReport {
  total: number
  by_stage: { stage: Stage; count: number }[]
  completion_rate: number | null
  avg_hours_to_complete: number | null
  awaiting_signature: number
  awaiting_you: number
  sent_last_30_days: number
  completed_last_30_days: number
  templates: { template_name: string; sent: number; completed: number }[]
}

export interface RecipientInput {
  email: string
  first_name: string
  last_name: string
}

export interface SendInput {
  template_id: string
  name?: string
  recipients: RecipientInput[]
  subject?: string
  message?: string
  /** The template's dynamic fields, by tag id */
  values?: Record<string, string>
  /** Add me as the last signer, after everyone else */
  countersign?: boolean
}

export interface SigningSession {
  session_id: string
  url: string
  expires_in_seconds: number
}

export const esignApi = {
  setup: () => apiRequest<EsignSetup>("/esign/setup"),
  templates: () => apiRequest<EsignTemplate[]>("/esign/templates"),
  uploadTemplate: ({
    file,
    name,
    description,
    layout,
  }: {
    file: File
    name: string
    description: string
    /** null: the file has field tags */
    layout: SignatureLayout | null
  }) => {
    const form = new FormData()
    form.append("file", file)
    form.append("name", name)
    if (description.trim()) form.append("description", description.trim())
    form.append("placement", layout ? "position" : "tags")
    if (layout) for (const [k, v] of Object.entries(layout)) form.append(k, String(v))
    return apiRequest<EsignTemplate>("/esign/templates", { method: "POST", form })
  },
  deleteTemplate: (id: string) => apiRequest<void>(`/esign/templates/${id}`, { method: "DELETE" }),
  downloadTemplate: (t: EsignTemplate) => apiDownload(`/esign/templates/${t.id}/file`, t.filename),
  documents: (stage: Stage | null, search: string) => {
    const params = new URLSearchParams({ limit: "200" })
    if (stage) params.set("stage", stage)
    if (search.trim()) params.set("search", search.trim())
    return apiRequest<{ items: EsignDocument[]; total: number }>(`/esign/documents?${params}`)
  },
  document: (id: string) => apiRequest<EsignDocumentDetail>(`/esign/documents/${id}`),
  send: (body: SendInput) => apiRequest<EsignDocument>("/esign/documents", { method: "POST", json: body }),
  refresh: (id: string) => apiRequest<EsignDocumentDetail>(`/esign/documents/${id}/refresh`, { method: "POST" }),
  countersign: (id: string) => apiRequest<SigningSession>(`/esign/documents/${id}/countersign`, { method: "POST" }),
  retrySend: (id: string) => apiRequest<EsignDocument>(`/esign/documents/${id}/send`, { method: "POST" }),
  download: (d: EsignDocument) => apiDownload(`/esign/documents/${d.id}/download`, `${d.name}.pdf`),
  report: () => apiRequest<EsignReport>("/esign/report"),
}
