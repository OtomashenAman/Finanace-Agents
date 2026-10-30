import { useState } from "react"
import { FileJson, Landmark, Upload } from "lucide-react"

import { AppPage } from "@/components/layout/app-page"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { useDataSources } from "@/features/data-sources/hooks"
import { EntitySelect } from "@/features/entities/entity-select"
import { useEntities } from "@/features/entities/hooks"
import { cn } from "@/lib/utils"

import type { Collection, Snapshot, SnapshotImportResult } from "./api"
import { Card, DemoBadge, Empty, Field, LoadError, Loading, PodTabs } from "./components/bits"
import { attempt, selectClass } from "./ui"
import {
  useImportBankStatement,
  useImportJson,
  useImportQuickBooks,
  useSnapshotRows,
  useSnapshots,
  useWorkflows,
} from "./hooks"
import { COLLECTION_LABEL, formatDateTime, shortHash } from "./labels"

function imported(result: SnapshotImportResult): string {
  return result.created ? "Snapshot imported." : "Identical content was already imported: using that snapshot."
}

function JsonImport() {
  const { data: entities = [] } = useEntities()
  const [entityId, setEntityId] = useState<string | null>(null)
  const [file, setFile] = useState<File | null>(null)
  const importJson = useImportJson()
  return (
    <form
      className="space-y-3"
      onSubmit={(e) => {
        e.preventDefault()
        if (file && entityId) void attempt(() => importJson.mutateAsync({ file, entityId }), imported)
      }}
    >
      <Field label="Legal entity">
        <EntitySelect entities={entities} value={entityId} onChange={setEntityId} className="w-full" />
      </Field>
      <Field label="Normalized export (JSON)" hint="Read-only QuickBooks Desktop / Enterprise export, at most 5 MB.">
        <Input type="file" accept=".json,application/json" onChange={(e) => setFile(e.target.files?.[0] ?? null)} />
      </Field>
      <Button type="submit" size="sm" disabled={!file || !entityId || importJson.isPending}>
        <FileJson /> Import export
      </Button>
    </form>
  )
}

function QuickBooksImport() {
  const { data: entities = [] } = useEntities()
  const { data: sources = [] } = useDataSources()
  const connections = sources.filter((s) => s.kind === "quickbooks" && s.last_synced_at)
  const [entityId, setEntityId] = useState<string | null>(null)
  const [sourceId, setSourceId] = useState("")
  const [currency, setCurrency] = useState("USD")
  const [basis, setBasis] = useState("Accrual")
  const importQb = useImportQuickBooks()
  if (!connections.length) {
    return <Empty>Connect and sync QuickBooks on the Data Sources page to copy it here (read only).</Empty>
  }
  return (
    <form
      className="space-y-3"
      onSubmit={(e) => {
        e.preventDefault()
        if (entityId && sourceId)
          void attempt(
            () =>
              importQb.mutateAsync({ data_source_id: sourceId, entity_id: entityId, currency, basis }),
            imported,
          )
      }}
    >
      <Field label="QuickBooks connection">
        <select className={selectClass} value={sourceId} onChange={(e) => setSourceId(e.target.value)}>
          <option value="">Choose…</option>
          {connections.map((s) => (
            <option key={s.id} value={s.id}>
              {s.name}
              {s.environment === "sandbox" ? " (sandbox: demo data)" : ""}
            </option>
          ))}
        </select>
      </Field>
      <Field label="Legal entity">
        <EntitySelect entities={entities} value={entityId} onChange={setEntityId} className="w-full" />
      </Field>
      <div className="grid grid-cols-2 gap-3">
        <Field label="Home currency">
          <Input value={currency} maxLength={3} onChange={(e) => setCurrency(e.target.value.toUpperCase())} />
        </Field>
        <Field label="Basis">
          <select className={selectClass} value={basis} onChange={(e) => setBasis(e.target.value)}>
            <option>Accrual</option>
            <option>Cash</option>
          </select>
        </Field>
      </div>
      <Button type="submit" size="sm" disabled={!entityId || !sourceId || importQb.isPending}>
        <Landmark /> Freeze a snapshot
      </Button>
      <p className="text-xs text-muted-foreground">
        Copies customers, invoices, payments and accounts as last synced. Nothing is written to QuickBooks.
      </p>
    </form>
  )
}

function BankStatement({ snapshot }: { snapshot: Snapshot }) {
  const [file, setFile] = useState<File | null>(null)
  const importCsv = useImportBankStatement()
  return (
    <form
      className="flex flex-wrap items-end gap-2"
      onSubmit={(e) => {
        e.preventDefault()
        if (file)
          void attempt(() => importCsv.mutateAsync({ snapshotId: snapshot.id, file }), imported)
      }}
    >
      <Field label="Add a bank statement (CSV)" hint="reference, payer, date, amount, currency, cleared. Creates a new snapshot.">
        <Input type="file" accept=".csv,text/csv" onChange={(e) => setFile(e.target.files?.[0] ?? null)} />
      </Field>
      <Button type="submit" size="sm" variant="outline" disabled={!file || importCsv.isPending}>
        <Upload /> Add statement
      </Button>
    </form>
  )
}

function Rows({ snapshot }: { snapshot: Snapshot }) {
  const [collection, setCollection] = useState<Collection | null>(snapshot.coverage[0] ?? null)
  const rows = useSnapshotRows(snapshot.id, collection)
  const data = rows.data?.rows ?? []
  const columns = [...new Set(data.flatMap((r) => Object.keys(r)))].slice(0, 9)
  return (
    <div className="space-y-3">
      <div className="flex flex-wrap gap-1">
        {snapshot.coverage.map((c) => (
          <button
            key={c}
            type="button"
            onClick={() => setCollection(c)}
            className={cn(
              "rounded-full border px-3 py-1 text-xs",
              c === collection ? "border-primary bg-primary/10 text-primary" : "text-muted-foreground hover:text-foreground",
            )}
          >
            {COLLECTION_LABEL[c]} ({snapshot.row_counts[c] ?? 0})
          </button>
        ))}
      </div>
      {rows.isError && <LoadError what="these rows (your roles may not include them)" />}
      {rows.isPending && collection && <Loading what="rows" />}
      {data.length > 0 && (
        <div className="max-h-80 overflow-auto rounded border">
          <table className="w-full text-xs">
            <thead className="sticky top-0 bg-secondary">
              <tr>
                {columns.map((c) => (
                  <th key={c} className="px-2 py-1.5 text-left font-semibold">
                    {c}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody className="divide-y">
              {data.map((row, i) => (
                <tr key={i}>
                  {columns.map((c) => (
                    <td key={c} className="max-w-[220px] truncate px-2 py-1.5" title={JSON.stringify(row[c])}>
                      {typeof row[c] === "object" ? JSON.stringify(row[c]) : String(row[c] ?? "")}
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

/** Immutable source snapshots: what every case calculates from. */
export function SourcesPage() {
  const { data: workflows = [] } = useWorkflows()
  const canImport = workflows.some((w) => w.my_capacities.includes("poster"))
  const snapshots = useSnapshots()
  const [openId, setOpenId] = useState<string | null>(null)

  return (
    <AppPage
      title="Service POD"
      subtitle="Read-only source snapshots. Imported data is never changed; a refresh is a new snapshot."
    >
      <PodTabs />
      <div className="grid gap-6 lg:grid-cols-[minmax(0,1fr)_340px]">
        <Card title="Snapshots" hint="Newest first. Missing collections stay missing: workflows that need them refuse the snapshot.">
          {snapshots.isPending && <Loading what="snapshots" />}
          {snapshots.isError && <LoadError what="snapshots" />}
          {snapshots.data?.length === 0 && <Empty>No snapshots yet.</Empty>}
          <ul className="divide-y">
            {snapshots.data?.map((s) => (
              <li key={s.id} className="py-3">
                <button type="button" className="w-full text-left" onClick={() => setOpenId(openId === s.id ? null : s.id)}>
                  <p className="flex flex-wrap items-center gap-2">
                    <span className="font-semibold text-brand-navy">{s.company_name}</span>
                    <span className="text-xs text-muted-foreground">
                      {s.entity.code} · {s.currency} · {s.basis} · as of {s.as_of}
                    </span>
                    {s.is_demo && <DemoBadge />}
                  </p>
                  <p className="mt-0.5 text-xs text-muted-foreground">
                    {s.source_type.replace("_", " ")} · {s.coverage.length} collections · imported by {s.imported_by}{" "}
                    {formatDateTime(s.imported_at)} · sha256 {shortHash(s.sha256)}
                    {s.parent_id && " · extends an earlier snapshot"}
                  </p>
                </button>
                {openId === s.id && (
                  <div className="mt-3 space-y-4 rounded-md bg-secondary/30 p-3">
                    <p className="text-xs break-all text-muted-foreground">Source: {s.source_reference}</p>
                    <Rows snapshot={s} />
                    {canImport && <BankStatement snapshot={s} />}
                  </div>
                )}
              </li>
            ))}
          </ul>
        </Card>
        {canImport ? (
          <div className="space-y-6">
            <Card title="Import an export">
              <JsonImport />
            </Card>
            <Card title="From QuickBooks Online">
              <QuickBooksImport />
            </Card>
          </div>
        ) : (
          <Card title="Importing">
            <p className="text-sm text-muted-foreground">A Finance Admin with posting rights imports source data.</p>
          </Card>
        )}
      </div>
    </AppPage>
  )
}
