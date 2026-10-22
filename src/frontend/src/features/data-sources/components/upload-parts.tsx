import { Label } from "@/components/ui/label"

import type { ColumnMapping, RecordType, RecordTypeInfo, UploadPreview } from "../api"
import { fieldLabel } from "../labels"

export const SELECT =
  "flex h-10 w-full rounded-md border border-input bg-background px-3 text-sm focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/20 focus-visible:outline-none disabled:opacity-50"

/** "What's in the file": one record type, or a workbook with one sheet per type */
export const WORKBOOK = "workbook"
export type UploadKind = RecordType | typeof WORKBOOK

export function KindSelect({
  value,
  onChange,
  recordTypes,
  disabled,
}: {
  value: UploadKind
  onChange: (kind: UploadKind) => void
  recordTypes: RecordTypeInfo[]
  disabled?: boolean
}) {
  return (
    <div className="space-y-2">
      <Label htmlFor="upload-type">What's in the file</Label>
      <select
        id="upload-type"
        className={SELECT}
        value={value}
        onChange={(e) => onChange(e.target.value as UploadKind)}
        disabled={disabled}
      >
        <option value={WORKBOOK}>Several types, one sheet each (XLSX)</option>
        {recordTypes.map((t) => (
          <option key={t.type} value={t.type}>
            {t.label}
          </option>
        ))}
      </select>
    </div>
  )
}

export function PreviewTable({ preview }: { preview: UploadPreview }) {
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

/** One select per field: which column of the file holds it */
export function MappingGrid({
  idPrefix,
  fields,
  headers,
  mapping,
  onChange,
  disabled,
}: {
  idPrefix: string
  fields: RecordTypeInfo["fields"]
  headers: string[]
  mapping: ColumnMapping
  onChange: (mapping: ColumnMapping) => void
  disabled?: boolean
}) {
  return (
    <div className="grid gap-3 sm:grid-cols-2">
      {fields.map((f) => (
        <div key={f.name} className="grid grid-cols-[minmax(0,1fr)_minmax(0,1fr)] items-center gap-3">
          <Label htmlFor={`${idPrefix}-${f.name}`} className="text-sm font-normal">
            {fieldLabel(f.name)}
            {f.required && <span className="text-destructive"> *</span>}
          </Label>
          <select
            id={`${idPrefix}-${f.name}`}
            className={SELECT}
            value={mapping[f.name] ?? ""}
            onChange={(e) => onChange({ ...mapping, [f.name]: e.target.value || null })}
            disabled={disabled}
          >
            <option value="">Not in file</option>
            {headers.map((h) => (
              <option key={h} value={h}>
                {h}
              </option>
            ))}
          </select>
        </div>
      ))}
    </div>
  )
}

/** "12 row(s): 11 valid, 1 with problems" and the problems */
export function RowCounts({ preview }: { preview: UploadPreview }) {
  return (
    <>
      <p className="text-sm">
        <span className="font-semibold">{preview.row_count.toLocaleString()}</span> row(s):{" "}
        <span className="font-semibold text-emerald-700">{preview.valid_count.toLocaleString()} valid</span>
        {preview.error_count > 0 && (
          <>
            , <span className="font-semibold text-destructive">{preview.error_count.toLocaleString()} with problems</span>
          </>
        )}
      </p>
      {preview.errors.length > 0 && (
        <ul className="max-h-40 space-y-1 overflow-y-auto rounded-md border bg-destructive/5 p-3 text-xs text-destructive">
          {preview.errors.map((e) => (
            <li key={e}>{e}</li>
          ))}
        </ul>
      )}
    </>
  )
}
