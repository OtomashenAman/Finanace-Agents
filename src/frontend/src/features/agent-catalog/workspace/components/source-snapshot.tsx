import { Database } from "lucide-react"

import { fieldLabel, RECORD_NOUN } from "@/features/data-sources/labels"

import type { RunSource } from "../api"
import { formatDateTime } from "../format"

type Row = Record<string, unknown>

function display(value: unknown): string {
  if (value === null || value === undefined || value === "") return "—"
  if (typeof value === "boolean") return value ? "Yes" : "No"
  return String(value)
}

/** "opening_cash" -> "Opening cash", unless it's a known record field */
function label(name: string): string {
  const known = fieldLabel(name)
  if (known !== name) return known.replace(/ \(.*\)$/, "")
  const words = name.replace(/_/g, " ")
  return words.charAt(0).toUpperCase() + words.slice(1)
}

function RecordCard({ title, record }: { title: string; record: Row }) {
  return (
    <div className="rounded-md border bg-background p-3">
      <p className="text-xs font-semibold tracking-wide text-muted-foreground uppercase">{title}</p>
      <dl className="mt-2 space-y-1 text-sm">
        {Object.entries(record)
          .filter(([name]) => name !== "external_id")
          .map(([name, value]) => (
            <div key={name} className="flex justify-between gap-3">
              <dt className="text-muted-foreground">{label(name)}</dt>
              <dd className="text-right font-medium break-all">{display(value)}</dd>
            </div>
          ))}
      </dl>
    </div>
  )
}

/** The records behind a total, e.g. the invoices counted as expected inflows */
function RecordTable({ title, rows }: { title: string; rows: Row[] }) {
  const columns = Object.keys(rows[0] ?? {}).filter((name) => name !== "external_id")
  return (
    <div className="rounded-md border bg-background p-3 sm:col-span-2">
      <p className="text-xs font-semibold tracking-wide text-muted-foreground uppercase">
        {title} ({rows.length})
      </p>
      {rows.length === 0 ? (
        <p className="mt-2 text-sm text-muted-foreground">None</p>
      ) : (
        <div className="mt-2 overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="text-left text-xs text-muted-foreground">
                {columns.map((c) => (
                  <th key={c} scope="col" className="pr-3 pb-1 font-medium whitespace-nowrap">
                    {label(c)}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {rows.map((row, i) => (
                <tr key={String(row.external_id ?? i)} className="border-t">
                  {columns.map((c) => (
                    <td key={c} className="py-1 pr-3 whitespace-nowrap tabular-nums">
                      {display(row[c])}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}

/** The data source records a run was prefilled from, as frozen when they were picked. */
export function SourceSnapshot({ source }: { source: RunSource }) {
  return (
    <section aria-label="Source data">
      <h3 className="flex items-center gap-2 text-sm font-semibold text-brand-navy">
        <Database className="size-4" aria-hidden />
        Source data
      </h3>
      <p className="mt-1 text-sm text-muted-foreground">
        {source.source_kind === "quickbooks" ? "QuickBooks" : "Upload"}: {source.source_name}
        {source.source_id === null && " (since removed by the preparer)"}. Captured {formatDateTime(source.captured_at)}
        {source.source_synced_at && `, data synced ${formatDateTime(source.source_synced_at)}`}.
      </p>
      <div className="mt-3 grid gap-3 sm:grid-cols-2">
        {Object.entries(source.records).map(([type, value]) => {
          const title = RECORD_NOUN[type] ?? label(type)
          return Array.isArray(value) ? (
            <RecordTable key={type} title={title} rows={value as Row[]} />
          ) : (
            <RecordCard key={type} title={title} record={value as Row} />
          )
        })}
      </div>
    </section>
  )
}
