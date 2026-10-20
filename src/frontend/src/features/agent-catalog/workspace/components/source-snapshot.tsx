import { Database } from "lucide-react"

import { fieldLabel, RECORD_NOUN } from "@/features/data-sources/labels"

import type { RunSource } from "../api"
import { formatDateTime } from "../format"

function display(value: unknown): string {
  if (value === null || value === undefined || value === "") return "—"
  if (typeof value === "boolean") return value ? "Yes" : "No"
  return String(value)
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
        {Object.entries(source.records).map(([type, record]) => (
          <div key={type} className="rounded-md border bg-background p-3">
            <p className="text-xs font-semibold tracking-wide text-muted-foreground uppercase">{RECORD_NOUN[type] ?? type}</p>
            <dl className="mt-2 space-y-1 text-sm">
              {Object.entries(record)
                .filter(([name]) => name !== "external_id")
                .map(([name, value]) => (
                  <div key={name} className="flex justify-between gap-3">
                    <dt className="text-muted-foreground">{fieldLabel(name).replace(/ \(.*\)$/, "")}</dt>
                    <dd className="text-right font-medium break-all">{display(value)}</dd>
                  </div>
                ))}
            </dl>
          </div>
        ))}
      </div>
    </section>
  )
}
