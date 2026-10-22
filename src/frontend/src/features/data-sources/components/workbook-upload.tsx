import { type ReactNode, useState } from "react"
import { LoaderCircle, Upload } from "lucide-react"
import { toast } from "sonner"

import { Alert } from "@/components/ui/alert"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { errorMessage } from "@/lib/api"
import { cn } from "@/lib/utils"

import type { RecordType, RecordTypeInfo, SheetChoices, SheetPreview, WorkbookPreview } from "../api"
import { usePreviewWorkbook, useUploadWorkbook } from "../hooks"
import { RECORD_LABELS } from "../labels"
import { MappingGrid, PreviewTable, RowCounts, SELECT } from "./upload-parts"

const SKIP = ""

/** The choices a preview was made with: each sheet's type and mapping */
function choicesOf(preview: WorkbookPreview): SheetChoices {
  return Object.fromEntries(
    preview.sheets.map((s) => [s.sheet, { record_type: s.record_type, mapping: s.preview?.mapping ?? null }]),
  )
}

function SheetBlock({
  sheet,
  recordTypes,
  choice,
  onType,
  onMapping,
  disabled,
}: {
  sheet: SheetPreview
  recordTypes: RecordTypeInfo[]
  choice: SheetChoices[string]
  onType: (type: RecordType | null) => void
  onMapping: (mapping: NonNullable<SheetChoices[string]["mapping"]>) => void
  disabled: boolean
}) {
  const preview = sheet.preview
  const fields = recordTypes.find((t) => t.type === choice.record_type)?.fields ?? []
  const id = `sheet-${sheet.sheet.replace(/\W+/g, "-")}`
  const problem = preview !== null && (preview.valid_count === 0 || preview.error_count > 0)

  return (
    <li className={cn("rounded-md border p-4", problem && "border-destructive/40")}>
      <div className="grid gap-3 sm:grid-cols-[minmax(0,1fr)_minmax(0,16rem)] sm:items-center">
        <div className="min-w-0">
          <p className="truncate font-semibold text-brand-navy" title={sheet.sheet}>
            {sheet.sheet}
          </p>
          <p className="text-xs text-muted-foreground">
            {preview
              ? `${preview.row_count.toLocaleString()} row(s): ${preview.valid_count.toLocaleString()} valid` +
                (preview.error_count ? `, ${preview.error_count.toLocaleString()} with problems` : "")
              : sheet.note}
          </p>
        </div>
        <div>
          <Label htmlFor={`${id}-type`} className="sr-only">
            Type of sheet {sheet.sheet}
          </Label>
          <select
            id={`${id}-type`}
            className={SELECT}
            value={choice.record_type ?? SKIP}
            onChange={(e) => onType((e.target.value || null) as RecordType | null)}
            disabled={disabled || sheet.empty}
          >
            <option value={SKIP}>Skip this sheet</option>
            {recordTypes.map((t) => (
              <option key={t.type} value={t.type}>
                {RECORD_LABELS[t.type]}
              </option>
            ))}
          </select>
        </div>
      </div>

      {preview && choice.mapping && (
        <details className="mt-3" open={problem}>
          <summary className="cursor-pointer text-sm font-medium text-primary">Columns and preview</summary>
          <div className="mt-3 space-y-3">
            <MappingGrid
              idPrefix={`${id}-map`}
              fields={fields}
              headers={preview.headers}
              mapping={choice.mapping}
              onChange={onMapping}
              disabled={disabled}
            />
            <RowCounts preview={preview} />
            <PreviewTable preview={preview} />
          </div>
        </details>
      )}
    </li>
  )
}

/** One XLSX, one sheet per record type (named after it), imported as one data source */
export function WorkbookUpload({
  recordTypes,
  kindSelect,
  onDone,
}: {
  recordTypes: RecordTypeInfo[]
  kindSelect: (disabled: boolean) => ReactNode
  onDone: () => void
}) {
  const preview = usePreviewWorkbook()
  const upload = useUploadWorkbook()
  const [file, setFile] = useState<File | null>(null)
  const [name, setName] = useState("")
  const [choices, setChoices] = useState<SheetChoices | null>(null)
  const [skipInvalid, setSkipInvalid] = useState(false)

  const result = preview.data
  const busy = preview.isPending || upload.isPending

  const runPreview = (picked: File, sheets?: SheetChoices) =>
    preview.mutate(
      { file: picked, sheets },
      {
        onSuccess: (p) => {
          setChoices(choicesOf(p))
          setSkipInvalid(false)
        },
      },
    )

  const onFile = (picked: File | null) => {
    setFile(picked)
    setChoices(null)
    preview.reset()
    if (picked) {
      if (!name) setName(picked.name.replace(/\.xlsx$/i, ""))
      runPreview(picked)
    }
  }

  // A new type reads the sheet again with the mapping suggested for that type
  const onType = (sheet: string, type: RecordType | null) => {
    if (!file || !choices) return
    runPreview(file, { ...choices, [sheet]: { record_type: type, mapping: null } })
  }

  const onImport = () => {
    if (!file || !choices) return
    upload.mutate(
      { file, sheets: choices, name: name.trim() || undefined, skipInvalid },
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

  const typed = (result?.sheets ?? []).filter((s) => s.preview !== null)
  const invalidRows = typed.reduce((n, s) => n + (s.preview?.error_count ?? 0), 0)
  const changed = result !== undefined && JSON.stringify(choices) !== JSON.stringify(choicesOf(result))
  const canImport =
    result !== undefined &&
    !changed &&
    result.errors.length === 0 &&
    typed.length > 0 &&
    typed.every((s) => (s.preview?.valid_count ?? 0) > 0) &&
    (invalidRows === 0 || skipInvalid)

  return (
    <div className="space-y-5">
      <p className="text-sm text-muted-foreground">
        One XLSX file, one sheet per type, each named after its type (e.g. <em>Bills</em>, <em>Customer invoices</em>,{" "}
        <em>Profit and loss</em>), first row as column names. Everything is imported as one data source.
      </p>

      <div className="grid gap-4 sm:grid-cols-3">
        {kindSelect(busy)}
        <div className="space-y-2">
          <Label htmlFor="workbook-file">File</Label>
          <Input
            id="workbook-file"
            type="file"
            accept=".xlsx"
            className="h-10 py-1.5 text-sm"
            onChange={(e) => onFile(e.target.files?.[0] ?? null)}
            disabled={busy}
          />
        </div>
        <div className="space-y-2">
          <Label htmlFor="workbook-name">Name</Label>
          <Input
            id="workbook-name"
            value={name}
            onChange={(e) => setName(e.target.value)}
            maxLength={200}
            placeholder="e.g. October books"
            className="h-10 text-sm"
          />
        </div>
      </div>

      {preview.isPending && (
        <p className="flex items-center gap-2 text-sm text-muted-foreground" role="status">
          <LoaderCircle className="size-4 animate-spin" aria-hidden /> Reading the sheets…
        </p>
      )}
      {preview.error && <Alert>{errorMessage(preview.error, "Couldn't read the file.")}</Alert>}
      {upload.error && <Alert>{errorMessage(upload.error, "Couldn't import the file.")}</Alert>}

      {result && choices && (
        <div className="space-y-3">
          <h3 className="text-sm font-semibold text-brand-navy">Sheets</h3>
          {result.errors.map((e) => (
            <Alert key={e}>{e}</Alert>
          ))}
          <ul className="space-y-3">
            {result.sheets.map((s) => (
              <SheetBlock
                key={s.sheet}
                sheet={s}
                recordTypes={recordTypes}
                choice={choices[s.sheet]}
                onType={(type) => onType(s.sheet, type)}
                onMapping={(mapping) => setChoices({ ...choices, [s.sheet]: { ...choices[s.sheet], mapping } })}
                disabled={busy}
              />
            ))}
          </ul>
          {changed && file && (
            <Button type="button" size="sm" variant="outline" onClick={() => runPreview(file, choices)} disabled={busy}>
              Check mapping
            </Button>
          )}
        </div>
      )}

      <div className="flex flex-wrap items-center gap-3 border-t pt-5">
        <Button type="button" onClick={onImport} disabled={!canImport || busy}>
          {upload.isPending ? <LoaderCircle className="animate-spin" aria-hidden /> : <Upload aria-hidden />}
          Import
        </Button>
        <Button type="button" variant="outline" onClick={onDone} disabled={upload.isPending}>
          Cancel
        </Button>
        {result && invalidRows > 0 && !changed && typed.every((s) => (s.preview?.valid_count ?? 0) > 0) && (
          <label className={cn("flex items-center gap-2 text-sm", busy && "opacity-50")}>
            <input
              type="checkbox"
              className="size-4 accent-primary"
              checked={skipInvalid}
              onChange={(e) => setSkipInvalid(e.target.checked)}
              disabled={busy}
            />
            Import the valid rows, skip the {invalidRows.toLocaleString()} with problems
          </label>
        )}
      </div>
    </div>
  )
}
