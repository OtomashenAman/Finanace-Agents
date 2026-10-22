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

import type { ColumnMapping, RecordType, RecordTypeInfo } from "../api"
import { usePreviewUpload, useRecordTypes, useUpload } from "../hooks"
import { KindSelect, MappingGrid, PreviewTable, RowCounts, type UploadKind, WORKBOOK } from "./upload-parts"
import { WorkbookUpload } from "./workbook-upload"

/** A CSV or XLSX (first sheet) holding one record type */
function SingleTypeUpload({
  initialType,
  recordTypes,
  onKind,
  onDone,
}: {
  initialType: RecordType
  recordTypes: RecordTypeInfo[]
  onKind: (kind: UploadKind) => void
  onDone: () => void
}) {
  const preview = usePreviewUpload()
  const upload = useUpload()
  const [recordType, setRecordType] = useState<RecordType>(initialType)
  const [file, setFile] = useState<File | null>(null)
  const [name, setName] = useState("")
  const [mapping, setMapping] = useState<ColumnMapping | null>(null)
  const [skipInvalid, setSkipInvalid] = useState(false)

  const result = preview.data
  const fields = recordTypes.find((t) => t.type === recordType)?.fields ?? []
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

  const onType = (kind: UploadKind) => {
    if (kind === WORKBOOK) {
      onKind(kind)
      return
    }
    setRecordType(kind)
    setMapping(null)
    if (file) runPreview({ file, recordType: kind })
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
    <div className="space-y-5">
      <p className="text-sm text-muted-foreground">
        CSV or XLSX, first row as column names. Only the records are kept, never the file itself. Dates as
        YYYY-MM-DD or DD/MM/YYYY.
      </p>

      <div className="grid gap-4 sm:grid-cols-3">
        <KindSelect value={recordType} onChange={onType} recordTypes={recordTypes} disabled={busy} />
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
            <div className="mt-3">
              <MappingGrid
                idPrefix="map"
                fields={fields}
                headers={result.headers}
                mapping={mapping}
                onChange={setMapping}
                disabled={busy}
              />
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
            <RowCounts preview={result} />
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
  )
}

export function UploadWizard({ onDone }: { onDone: () => void }) {
  const recordTypes = useRecordTypes().data ?? []
  // A workbook with every type is the usual way to load data without QuickBooks
  const [kind, setKind] = useState<UploadKind>(WORKBOOK)

  return (
    <Panel title="Upload finance data">
      {kind === WORKBOOK ? (
        <WorkbookUpload
          recordTypes={recordTypes}
          kindSelect={(disabled) => (
            <KindSelect value={WORKBOOK} onChange={setKind} recordTypes={recordTypes} disabled={disabled} />
          )}
          onDone={onDone}
        />
      ) : (
        <SingleTypeUpload
          key={kind}
          initialType={kind}
          recordTypes={recordTypes}
          onKind={setKind}
          onDone={onDone}
        />
      )}
    </Panel>
  )
}
