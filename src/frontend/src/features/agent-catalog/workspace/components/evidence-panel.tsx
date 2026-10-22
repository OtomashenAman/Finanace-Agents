import { useRef, useState, type DragEvent } from "react"
import { FileText, LoaderCircle, Trash2, TriangleAlert, Upload } from "lucide-react"
import { toast } from "sonner"

import { ApiError } from "@/lib/api"
import { cn } from "@/lib/utils"

import { runsApi, type RunDetail, type RunDocument } from "../api"
import { formatBytes } from "../format"
import { useRemoveDocument, useUploadDocument } from "../hooks"

const ACCEPT = ".pdf,.xlsx,.csv,.tsv,.txt,.docx"

function DocumentItem({
  agentKey,
  run,
  document,
  canEdit,
}: {
  agentKey: string
  run: RunDetail
  document: RunDocument
  canEdit: boolean
}) {
  const remove = useRemoveDocument(agentKey, run.id)
  const [fullText, setFullText] = useState<string | null>(null)
  const [loading, setLoading] = useState(false)

  const loadFullText = async () => {
    setLoading(true)
    try {
      setFullText((await runsApi.documentText(agentKey, run.id, document.id)).extracted_text)
    } catch {
      toast.error("Couldn't load the document text")
    } finally {
      setLoading(false)
    }
  }

  const detail = [
    document.extractor.toUpperCase(),
    document.page_count !== null &&
      `${document.page_count} ${document.extractor === "xlsx" ? "sheet" : "page"}${document.page_count === 1 ? "" : "s"}`,
    `${document.char_count.toLocaleString()} chars`,
    formatBytes(document.size_bytes),
  ]
    .filter(Boolean)
    .join(" · ")

  return (
    <li className="rounded-md border bg-background p-3">
      <div className="flex items-start gap-2.5">
        <FileText className="mt-0.5 size-4 shrink-0 text-primary" aria-hidden />
        <div className="min-w-0 flex-1">
          <p className="truncate text-sm font-medium" title={document.filename}>
            {document.filename}
          </p>
          <p className="text-xs text-muted-foreground">{detail}</p>
        </div>
        {canEdit && (
          <button
            type="button"
            onClick={() => remove.mutate(document.id, { onError: () => toast.error("Couldn't remove the document") })}
            disabled={remove.isPending}
            className="rounded p-1 text-muted-foreground hover:bg-secondary hover:text-destructive disabled:opacity-50"
            aria-label={`Remove ${document.filename}`}
          >
            <Trash2 className="size-4" />
          </button>
        )}
      </div>
      {document.warnings.map((warning) => (
        <p key={warning} className="mt-2 flex items-start gap-1.5 text-xs text-amber-800">
          <TriangleAlert className="mt-px size-3.5 shrink-0" aria-hidden />
          {warning}
        </p>
      ))}
      <details className="mt-2 text-xs">
        <summary className="cursor-pointer text-primary">Extracted text</summary>
        <pre className="mt-2 max-h-64 overflow-auto rounded bg-muted p-2.5 font-sans whitespace-pre-wrap text-foreground">
          {fullText ?? document.text_preview}
        </pre>
        {fullText === null && document.char_count > document.text_preview.length && (
          <button
            type="button"
            onClick={() => void loadFullText()}
            disabled={loading}
            className="mt-1.5 text-primary hover:underline disabled:opacity-50"
          >
            {loading ? "Loading…" : "Show full text"}
          </button>
        )}
      </details>
    </li>
  )
}

interface EvidencePanelProps {
  agentKey: string
  run: RunDetail
  canEdit: boolean
}

/** Upload area + extracted documents. Files are never stored, only their text. */
export function EvidencePanel({ agentKey, run, canEdit }: EvidencePanelProps) {
  const upload = useUploadDocument(agentKey, run.id)
  const inputRef = useRef<HTMLInputElement>(null)
  const [dragging, setDragging] = useState(false)

  const send = (files: FileList | null) => {
    for (const file of Array.from(files ?? [])) {
      upload.mutate(file, {
        onSuccess: () => toast.success(`${file.name}: text extracted`),
        onError: (error) =>
          toast.error(`${file.name} was not added`, {
            description: error instanceof ApiError ? error.message : "Upload failed",
          }),
      })
    }
    if (inputRef.current) inputRef.current.value = ""
  }

  const onDrop = (event: DragEvent) => {
    event.preventDefault()
    setDragging(false)
    if (canEdit) send(event.dataTransfer.files)
  }

  return (
    <div className="space-y-3">
      <h3 className="text-sm font-semibold text-brand-navy">Supporting documents</h3>
      {canEdit && (
        <label
          onDragOver={(e) => {
            e.preventDefault()
            setDragging(true)
          }}
          onDragLeave={() => setDragging(false)}
          onDrop={onDrop}
          className={cn(
            "flex cursor-pointer flex-col items-center gap-1 rounded-lg border-2 border-dashed px-4 py-6 text-center transition-colors",
            dragging ? "border-primary bg-primary/5" : "border-border bg-secondary/40 hover:border-primary/50",
          )}
        >
          {upload.isPending ? (
            <LoaderCircle className="size-5 animate-spin text-primary" aria-hidden />
          ) : (
            <Upload className="size-5 text-primary" aria-hidden />
          )}
          <span className="font-semibold text-primary">{upload.isPending ? "Extracting text…" : "Upload files"}</span>
          <span className="text-xs text-muted-foreground">PDF / XLSX / CSV / DOCX / TXT · text is extracted, files aren't stored</span>
          <input
            ref={inputRef}
            type="file"
            accept={ACCEPT}
            multiple
            className="sr-only"
            onChange={(e) => send(e.target.files)}
            disabled={upload.isPending}
          />
        </label>
      )}
      {run.documents.length > 0 ? (
        <ul className="space-y-2">
          {run.documents.map((document) => (
            <DocumentItem key={document.id} agentKey={agentKey} run={run} document={document} canEdit={canEdit} />
          ))}
        </ul>
      ) : (
        !canEdit && <p className="text-sm text-muted-foreground">No documents attached.</p>
      )}
    </div>
  )
}
