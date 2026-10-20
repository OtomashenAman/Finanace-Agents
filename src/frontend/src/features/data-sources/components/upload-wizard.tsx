import { useState } from "react"
import { LoaderCircle, Upload } from "lucide-react"
import { toast } from "sonner"

import { Alert } from "@/components/ui/alert"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Panel } from "@/features/agent-catalog/workspace/components/panel"
import { errorMessage } from "@/lib/api"
import { cn } from "@/lib/utils"

import type { ColumnMapping, RecordType, UploadPreview } from "../api"
import { usePreviewUpload, useRecordTypes, useUpload } from "../hooks"
import { fieldLabel } from "../labels"

const SELECT =
  "flex h-10 w-full rounded-md border border-input bg-background px-3 text-sm focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/20 focus-visible:outline-none disabled:opacity-50"

function PreviewTable({ preview }: { preview: UploadPreview }) {
  return (
    <div className="overflow-x-auto rounded-md border">
      <table className="w-full min-w-[480px] text-xs">
        <thead className="bg-secondary/60">
          <tr>
            {preview.headers.map((h) => (
              <th key={h} className="px-2.5 py-2 text-left font-semibold whitespace-nowrap">
                {h}
              </th>
            ))}
          </tr>
        </thead>
        <tbody className="divide-y">
          {preview.sample_rows.map((row, i) => (
            <tr key={i}>
              {row.map((cell, j) => (
                <td key={j} className="max-w-[180px] truncate px-2.5 py-1.5" title={cell}>
                  {cell}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

export function UploadWizard({ onDone }: { onDone: () => void }) {
  const recordTypes = useRecordTypes()
  const preview = usePreviewUpload()
  const upload = useUpload()
  const [recordType, setRecordType] = useState<RecordType>("bill")
  const [file, setFile] = useState<File | null>(null)
  const [name, setName] = useState("")
  const [mapping, setMapping] = useState<ColumnMapping | null>(null)
  const [skipInvalid, setSkipInvalid] = useState(false)

  const result = preview.data
  const fields = recordTypes.data?.find((t) => t.type === recordType)?.fields ?? []
  const busy = preview.isPending || upload.isPending

  const runPreview = (next: { file: File; recordType: RecordType; mapping?: ColumnMapping }) =>
    preview.mutate(next, {
      onSuccess: (p) => {
        setMapping(p.mapping)
        setSkipInvalid(false)
      },
    })

  const onFile = (picked: File | null) => {
    setFile(picked)
    setMapping(null)
    preview.reset()
    if (picked) {
      if (!name) setName(picked.name.replace(/\.(csv|xlsx)$/i, ""))
      runPreview({ file: picked, recordType })
    }
  }

  const onType = (type: RecordType) => {
    setRecordType(type)
    setMapping(null)
    if (file) runPreview({ file, recordType: type })
  }

  const onImport = () => {
    if (!file || !mapping) return
    upload.mutate(
      { file, recordType, mapping, name: name.trim() || undefined, skipInvalid },
      {
        onSuccess: (r) => {
          toast.success(
            `${r.imported.toLocaleString()} record(s) imported` + (r.skipped ? `, ${r.skipped} skipped` : ""),
          )
          onDone()
        },
      },
    )
  }

  const mappingChanged = result !== undefined && JSON.stringify(mapping) !== JSON.stringify(result.mapping)
  const canImport = result !== undefined && !mappingChanged && result.valid_count > 0 && (result.error_count === 0 || skipInvalid)

  return (
    <Panel title="Upload finance data">
      <div className="space-y-5">
        <p className="text-sm text-muted-foreground">
          CSV or XLSX, first row as column names. Only the records are kept, never the file itself. Dates as
          YYYY-MM-DD or DD/MM/YYYY.
        </p>

        <div className="grid gap-4 sm:grid-cols-3">
          <div className="space-y-2">
            <Label htmlFor="upload-type">What's in the file</Label>
            <select
              id="upload-type"
              className={SELECT}
              value={recordType}
              onChange={(e) => onType(e.target.value as RecordType)}
              disabled={busy}
            >
              {(recordTypes.data ?? []).map((t) => (
                <option key={t.type} value={t.type}>
                  {t.label}
                </option>
              ))}
            </select>
          </div>
          <div className="space-y-2">
            <Label htmlFor="upload-file">File</Label>
            <Input
              id="upload-file"
              type="file"
              accept=".csv,.xlsx"
              className="h-10 py-1.5 text-sm"
              onChange={(e) => onFile(e.target.files?.[0] ?? null)}
              disabled={busy}
            />
          </div>
          <div className="space-y-2">
            <Label htmlFor="upload-name">Name</Label>
            <Input
              id="upload-name"
              value={name}
              onChange={(e) => setName(e.target.value)}
              maxLength={200}
              placeholder="e.g. October AP bills"
              className="h-10 text-sm"
            />
          </div>
        </div>

        {preview.isPending && (
          <p className="flex items-center gap-2 text-sm text-muted-foreground" role="status">
            <LoaderCircle className="size-4 animate-spin" aria-hidden /> Reading the file…
          </p>
        )}
        {preview.error && <Alert>{errorMessage(preview.error, "Couldn't read the file.")}</Alert>}
        {upload.error && <Alert>{errorMessage(upload.error, "Couldn't import the file.")}</Alert>}

        {result && mapping && (
          <>
            <div>
              <h3 className="text-sm font-semibold text-brand-navy">Match columns to fields</h3>
              <div className="mt-3 grid gap-3 sm:grid-cols-2">
                {fields.map((f) => (
                  <div key={f.name} className="grid grid-cols-[minmax(0,1fr)_minmax(0,1fr)] items-center gap-3">
                    <Label htmlFor={`map-${f.name}`} className="text-sm font-normal">
                      {fieldLabel(f.name)}
                      {f.required && <span className="text-destructive"> *</span>}
                    </Label>
                    <select
                      id={`map-${f.name}`}
                      className={SELECT}
                      value={mapping[f.name] ?? ""}
                      onChange={(e) => setMapping({ ...mapping, [f.name]: e.target.value || null })}
                      disabled={busy}
                    >
                      <option value="">Not in file</option>
                      {result.headers.map((h) => (
                        <option key={h} value={h}>
                          {h}
                        </option>
                      ))}
                    </select>
                  </div>
                ))}
              </div>
              {mappingChanged && file && (
                <Button
                  type="button"
                  size="sm"
                  variant="outline"
                  className="mt-3"
                  onClick={() => runPreview({ file, recordType, mapping })}
                  disabled={busy}
                >
                  Check mapping
                </Button>
              )}
            </div>

            <div className="space-y-3">
              <p className="text-sm">
                <span className="font-semibold">{result.row_count.toLocaleString()}</span> row(s):{" "}
                <span className="font-semibold text-emerald-700">{result.valid_count.toLocaleString()} valid</span>
                {result.error_count > 0 && (
                  <>
                    , <span className="font-semibold text-destructive">{result.error_count.toLocaleString()} with problems</span>
                  </>
                )}
              </p>
              {result.errors.length > 0 && (
                <ul className="max-h-40 space-y-1 overflow-y-auto rounded-md border bg-destructive/5 p-3 text-xs text-destructive">
                  {result.errors.map((e) => (
                    <li key={e}>{e}</li>
                  ))}
                </ul>
              )}
              <PreviewTable preview={result} />
            </div>
          </>
        )}

        <div className="flex flex-wrap items-center gap-3 border-t pt-5">
          <Button type="button" onClick={onImport} disabled={!canImport || busy}>
            {upload.isPending ? <LoaderCircle className="animate-spin" aria-hidden /> : <Upload aria-hidden />}
            Import
          </Button>
          <Button type="button" variant="outline" onClick={onDone} disabled={upload.isPending}>
            Cancel
          </Button>
          {result && result.error_count > 0 && result.valid_count > 0 && !mappingChanged && (
            <label className={cn("flex items-center gap-2 text-sm", busy && "opacity-50")}>
              <input
                type="checkbox"
                className="size-4 accent-primary"
                checked={skipInvalid}
                onChange={(e) => setSkipInvalid(e.target.checked)}
                disabled={busy}
              />
              Import the {result.valid_count.toLocaleString()} valid row(s), skip the rest
            </label>
          )}
        </div>
      </div>
    </Panel>
  )
}
