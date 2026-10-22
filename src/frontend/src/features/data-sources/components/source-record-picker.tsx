import { useDeferredValue, useState } from "react"
import { Link } from "react-router"
import { Database, LoaderCircle, Search, Unlink } from "lucide-react"
import { toast } from "sonner"

import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import type { RunDetail } from "@/features/agent-catalog/workspace/api"
import { formatDateTime } from "@/features/agent-catalog/workspace/format"
import { useLinkSource, useUnlinkSource } from "@/features/agent-catalog/workspace/hooks"
import { errorMessage } from "@/lib/api"

import type { RecordType } from "../api"
import { useDataSources, useSourceRecords } from "../hooks"
import { RECORD_LABELS, RECORD_NOUN } from "../labels"

const SELECT =
  "flex h-10 w-full rounded-md border border-input bg-background px-3 text-sm focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/20 focus-visible:outline-none"

function money(value: string | null): string {
  if (value === null) return "—"
  return Number(value).toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })
}

interface PickerProps {
  agentKey: string
  run: RunDetail
  recordType: string
  /** Called with the prefilled run so the form can show the new values */
  onLinked: (run: RunDetail) => void
}

/** Prefill a run from a record of the user's own data sources (e.g. a QuickBooks bill). */
export function SourceRecordPicker({ agentKey, run, recordType, onLinked }: PickerProps) {
  const sources = useDataSources()
  const link = useLinkSource(agentKey, run.id)
  const unlink = useUnlinkSource(agentKey, run.id)
  const [picking, setPicking] = useState(run.source === null)
  const [sourceId, setSourceId] = useState<string | null>(null)
  const [search, setSearch] = useState("")
  const query = useDeferredValue(search.trim())

  const usable = (sources.data ?? []).filter((s) => (s.record_counts[recordType as RecordType] ?? 0) > 0)
  const selected = sourceId ?? usable[0]?.id ?? null
  const records = useSourceRecords(picking ? selected : null, recordType, query)
  const noun = RECORD_NOUN[recordType] ?? "record"
  const busy = link.isPending || unlink.isPending

  const use = (recordId: string) => {
    if (!selected) return
    link.mutate(
      { sourceId: selected, recordId },
      {
        onSuccess: (updated) => {
          setPicking(false)
          onLinked(updated)
          toast.success(`Prefilled from ${updated.source?.source_name ?? "your data source"}`, {
            description: "Check the values and complete any missing fields.",
          })
        },
        onError: (error) => toast.error(errorMessage(error, "Couldn't prefill the run")),
      },
    )
  }

  const onUnlink = () =>
    unlink.mutate(undefined, {
      onSuccess: () => {
        setPicking(true)
        toast.success("Unlinked: the values stay for you to edit")
      },
      onError: (error) => toast.error(errorMessage(error, "Couldn't unlink")),
    })

  return (
    <section className="rounded-md border bg-secondary/30 p-4" aria-label="Prefill from a data source">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h3 className="flex items-center gap-2 text-sm font-semibold text-brand-navy">
          <Database className="size-4" aria-hidden />
          Prefill from your data
        </h3>
        {run.source && !picking && (
          <div className="flex gap-1">
            <Button type="button" size="sm" variant="ghost" onClick={() => setPicking(true)} disabled={busy}>
              Pick another {noun}
            </Button>
            <Button type="button" size="sm" variant="ghost" onClick={onUnlink} disabled={busy}>
              <Unlink aria-hidden />
              Unlink
            </Button>
          </div>
        )}
      </div>

      {run.source && !picking && (
        <p className="mt-2 text-sm">
          From <span className="font-semibold">{run.source.source_name}</span>: {noun}{" "}
          <span className="font-semibold">{run.source.record_reference}</span>
          <span className="block text-xs text-muted-foreground">
            Captured {formatDateTime(run.source.captured_at)}; the reviewer sees this snapshot.
          </span>
        </p>
      )}

      {picking && (
        <div className="mt-3 space-y-3">
          {sources.isPending && <LoaderCircle className="size-4 animate-spin text-primary" aria-label="Loading" />}
          {sources.data && usable.length === 0 && (
            <p className="text-sm text-muted-foreground">
              None of your data sources has {RECORD_LABELS[recordType as RecordType]?.toLowerCase() ?? "records"} yet.{" "}
              <Link to="/data-sources" className="font-medium text-primary hover:underline">
                Connect QuickBooks or upload a file
              </Link>
              , or enter the values manually.
            </p>
          )}
          {usable.length > 0 && (
            <>
              <div className="grid gap-2 sm:grid-cols-2">
                <select
                  className={SELECT}
                  value={selected ?? ""}
                  onChange={(e) => setSourceId(e.target.value)}
                  aria-label="Data source"
                >
                  {usable.map((s) => (
                    <option key={s.id} value={s.id}>
                      {s.name}
                    </option>
                  ))}
                </select>
                <div className="relative">
                  <Search className="absolute top-1/2 left-3 size-4 -translate-y-1/2 text-muted-foreground" aria-hidden />
                  <Input
                    type="search"
                    value={search}
                    onChange={(e) => setSearch(e.target.value)}
                    placeholder={`Search ${noun} or vendor`}
                    aria-label={`Search ${noun}s`}
                    className="h-10 pl-9 text-sm"
                  />
                </div>
              </div>
              <ul className="max-h-64 divide-y overflow-y-auto rounded-md border bg-card">
                {records.isPending && (
                  <li className="flex justify-center p-4">
                    <LoaderCircle className="size-4 animate-spin text-primary" aria-label="Loading" />
                  </li>
                )}
                {records.data?.length === 0 && (
                  <li className="p-3 text-sm text-muted-foreground">No matching {noun}s.</li>
                )}
                {records.data?.map((r) => (
                  <li key={r.external_id} className="flex items-center justify-between gap-3 px-3 py-2 text-sm">
                    <div className="min-w-0">
                      <p className="truncate font-medium">{r.reference}</p>
                      <p className="truncate text-xs text-muted-foreground">
                        {[r.counterparty, r.txn_date].filter(Boolean).join(" · ")}
                      </p>
                    </div>
                    <span className="ml-auto shrink-0 tabular-nums">{money(r.amount)}</span>
                    <Button type="button" size="sm" variant="outline" onClick={() => use(r.external_id)} disabled={busy}>
                      Use
                    </Button>
                  </li>
                ))}
              </ul>
              {run.source && (
                <Button type="button" size="sm" variant="ghost" onClick={() => setPicking(false)}>
                  Keep {run.source.record_reference}
                </Button>
              )}
            </>
          )}
        </div>
      )}
    </section>
  )
}
