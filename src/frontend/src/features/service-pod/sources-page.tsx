import { useState } from "react"
import { Archive, ArchiveRestore, ChevronDown, ChevronRight, FileJson, History, Landmark, Trash2, Upload } from "lucide-react"

import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { useDataSources } from "@/features/data-sources/hooks"
import { EntitySelect } from "@/features/entities/entity-select"
import { useEntities } from "@/features/entities/hooks"
import { cn } from "@/lib/utils"

import type { Collection, Snapshot, SnapshotImportResult } from "./api"
import { Card, DemoBadge, Empty, Field, LoadError, Loading, Pill, PodTabs } from "./components/bits"
import { attempt, selectClass } from "./ui"
import {
  useArchiveSnapshot,
  useDeleteSnapshot,
  usePurgeSnapshot,
  useImportBankStatement,
  useImportJson,
  useImportQuickBooks,
  useRestoreSnapshot,
  useSnapshotDependents,
  useSnapshotRows,
  useSnapshots,
} from "./hooks"
import { COLLECTION_LABEL, formatDateTime, shortHash } from "./labels"
import { snapshotKey, splitLatest } from "./components/latest"
import { PurgeSummary } from "./components/purge-summary"
import { PodPage } from "./components/pod-page"

function imported(result: SnapshotImportResult): string {
  const head = result.created ? "Snapshot imported." : "Identical content was already imported: using that snapshot."
  // e.g. the P&L detail FP&A needs couldn't be read: say so, it isn't silently missing
  return result.notes?.length ? `${head} ${result.notes.join(" ")}` : head
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
      <Field
        label="Normalized export (Excel or JSON)"
        hint="A Company sheet plus one sheet per collection (Customers, Invoices, GL lines…), or the same as JSON. At most 5 MB."
      >
        <Input
          type="file"
          accept=".xlsx,.json,application/json,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
          onChange={(e) => setFile(e.target.files?.[0] ?? null)}
        />
      </Field>
      <Button type="submit" size="sm" disabled={!file || !entityId || importJson.isPending}>
        <FileJson /> Import
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

function BankStatementImport({ snapshots }: { snapshots: Snapshot[] }) {
  const activeSnapshots = snapshots.filter((s) => !s.archived)
  const [snapshotId, setSnapshotId] = useState<string>("")
  const [file, setFile] = useState<File | null>(null)
  const importCsv = useImportBankStatement()

  const selectedId = snapshotId || activeSnapshots[0]?.id || ""

  if (activeSnapshots.length === 0) {
    return <Empty>Import or freeze a snapshot first before attaching bank receipts.</Empty>
  }

  return (
    <form
      className="space-y-3"
      onSubmit={(e) => {
        e.preventDefault()
        if (file && selectedId)
          void attempt(() => importCsv.mutateAsync({ snapshotId: selectedId, file }), imported)
      }}
    >
      <Field label="Target snapshot" hint="Which snapshot to attach these bank receipts to">
        <select
          className={selectClass}
          value={selectedId}
          onChange={(e) => setSnapshotId(e.target.value)}
        >
          {activeSnapshots.map((s) => (
            <option key={s.id} value={s.id}>
              {s.company_name} ({s.source_type.replace("_", " ")}) · {s.as_of}
              {s.coverage.includes("bank_receipts") ? " [has receipts]" : " [no receipts]"}
            </option>
          ))}
        </select>
      </Field>
      <Field
        label="Bank statement (CSV)"
        hint="Headers required: reference, payer, date, amount, currency, cleared."
      >
        <Input
          type="file"
          accept=".csv,text/csv"
          onChange={(e) => setFile(e.target.files?.[0] ?? null)}
        />
      </Field>
      <Button type="submit" size="sm" disabled={!file || !selectedId || importCsv.isPending}>
        <Upload /> Attach to snapshot
      </Button>
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
      {rows.isError && <LoadError what="these rows" />}
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

/** Archive (hidden, kept as evidence) or, when nothing depends on it, delete a snapshot. */
function Removal({ snapshot }: { snapshot: Snapshot }) {
  const archive = useArchiveSnapshot()
  const restore = useRestoreSnapshot()
  const remove = useDeleteSnapshot()
  const purge = usePurgeSnapshot()
  const [how, setHow] = useState<"archive" | "delete" | "purge" | null>(null)
  const [reason, setReason] = useState("")
  const [confirm, setConfirm] = useState("")
  const preview = useSnapshotDependents(how === "purge" ? snapshot.id : null)
  const busy = archive.isPending || restore.isPending || remove.isPending || purge.isPending

  if (snapshot.archived) {
    return (
      <div className="flex flex-wrap items-center gap-2 border-t pt-3 text-xs">
        <span className="text-muted-foreground">
          Archived by {snapshot.archived_by} {formatDateTime(snapshot.archived_at)}: {snapshot.archived_reason}
        </span>
        <Button size="sm" variant="outline" disabled={busy} onClick={() => void attempt(() => restore.mutateAsync(snapshot.id), "Snapshot restored.")}>
          <ArchiveRestore /> Restore
        </Button>
      </div>
    )
  }
  return (
    <div className="space-y-2 border-t pt-3 text-xs">
      <div className="flex flex-wrap items-center gap-2">
        <Button size="sm" variant="outline" disabled={busy} onClick={() => setHow(how === "archive" ? null : "archive")}>
          <Archive /> Archive
        </Button>
        {snapshot.in_use ? (
          <Button size="sm" variant="outline" className="text-red-800" disabled={busy} onClick={() => setHow(how === "purge" ? null : "purge")}>
            <Trash2 /> Delete everything…
          </Button>
        ) : (
          <Button size="sm" variant="outline" className="text-red-800" disabled={busy} onClick={() => setHow(how === "delete" ? null : "delete")}>
            <Trash2 /> Delete
          </Button>
        )}
        <span className="text-muted-foreground">
          {snapshot.in_use ? `In use: ${snapshot.in_use}. Archive it, or delete it with everything on it.` : "Not used by any case: it can be deleted."}
        </span>
      </div>
      {how === "purge" && (
        <form
          className="space-y-2"
          onSubmit={(e) => {
            e.preventDefault()
            void attempt(
              () => purge.mutateAsync({ id: snapshot.id, reason, confirm }),
              (gone) => `Deleted ${gone.snapshots.length} snapshot(s) and ${gone.cases.length} case(s).`,
            ).then((gone) => gone && setHow(null))
          }}
        >
          {preview.isPending && <Loading what="what depends on it" />}
          {preview.data && <PurgeSummary preview={preview.data} />}
          <Input className="h-9 max-w-md" placeholder="Reason (kept in the audit trail)" value={reason} onChange={(e) => setReason(e.target.value)} />
          <Input className="h-9 max-w-md" placeholder={`Type "${snapshot.company_name}" to confirm`} value={confirm} onChange={(e) => setConfirm(e.target.value)} aria-label="Company name to confirm" />
          <Button
            type="submit"
            size="sm"
            variant="destructive"
            disabled={busy || !preview.data || reason.trim().length < 3 || confirm.trim().toLowerCase() !== snapshot.company_name.trim().toLowerCase()}
          >
            Delete everything
          </Button>
        </form>
      )}
      {(how === "archive" || how === "delete") && (
        <form
          className="flex flex-wrap gap-2"
          onSubmit={(e) => {
            e.preventDefault()
            void attempt(
              () =>
                (how === "archive"
                  ? archive.mutateAsync({ id: snapshot.id, reason })
                  : remove.mutateAsync({ id: snapshot.id, reason })
                ).then(() => true),
              how === "archive" ? "Snapshot archived." : "Snapshot deleted.",
            ).then((done) => done && setHow(null))
          }}
        >
          <Input className="h-9 max-w-sm" placeholder="Reason (kept in the audit trail)" value={reason} onChange={(e) => setReason(e.target.value)} />
          <Button type="submit" size="sm" variant={how === "delete" ? "destructive" : "default"} disabled={busy || reason.trim().length < 3}>
            {how === "archive" ? "Archive snapshot" : "Delete for good"}
          </Button>
        </form>
      )}
    </div>
  )
}

/** Immutable source snapshots: what every case calculates from. */
export function SourcesPage() {
  const [showArchived, setShowArchived] = useState(false)
  const snapshots = useSnapshots(showArchived)
  const [openId, setOpenId] = useState<string | null>(null)

  // The latest snapshot of each company first; earlier ones on request
  const [expanded, setExpanded] = useState<Set<string>>(new Set())
  const groups = splitLatest<Snapshot>(snapshots.data ?? [], snapshotKey)
  const rows = groups.latest.flatMap((s) => {
    const key = snapshotKey(s)
    const older = groups.older.get(key) ?? []
    return [
      { s, key, older, first: true },
      ...(expanded.has(key) ? older.map((o) => ({ s: o, key, older, first: false })) : []),
    ]
  })

  return (
    <PodPage
      title="Data sources"
      subtitle="Read-only source snapshots. Imported data is never changed; a refresh is a new snapshot."
    >
      <PodTabs />
      <div className="grid gap-6 lg:grid-cols-[minmax(0,1fr)_340px]">
        <Card
          title="Snapshots"
          hint="The latest snapshot of each company; earlier ones fold underneath. Missing collections stay missing: workflows that need them refuse the snapshot."
          actions={
            <label className="flex items-center gap-2 text-xs">
              <input type="checkbox" checked={showArchived} onChange={(e) => setShowArchived(e.target.checked)} />
              Show archived
            </label>
          }
        >
          {snapshots.isPending && <Loading what="snapshots" />}
          {snapshots.isError && <LoadError what="snapshots" />}
          {snapshots.data?.length === 0 && <Empty>No snapshots yet.</Empty>}
          <ul className="divide-y">
            {rows.map(({ s, key, older, first }) => {
              const hasReceipts = s.coverage.includes("bank_receipts")
              const isOpen = openId === s.id
              return (
                <li
                  key={s.id}
                  className={
                    first
                      ? "py-2.5"
                      : "relative ml-6 border-l-2 border-primary/20 py-1.5 pl-4 before:absolute before:-left-[5px] before:top-4 before:size-2 before:rounded-full before:bg-primary/50"
                  }
                >
                  <button
                    type="button"
                    className="flex w-full items-start justify-between gap-3 rounded-lg border border-transparent p-2.5 text-left transition-all hover:border-border/60 hover:bg-muted/40"
                    onClick={() => setOpenId(isOpen ? null : s.id)}
                  >
                    <div className="min-w-0 flex-1">
                      <p className="flex flex-wrap items-center gap-2">
                        <span className="font-semibold text-brand-navy dark:text-foreground">{s.company_name}</span>
                        <span className="text-xs text-muted-foreground font-mono">
                          {s.entity.code} · {s.currency} · {s.basis} · as of {s.as_of}
                        </span>
                        {s.is_demo && <DemoBadge />}
                        {s.archived && <Pill label="Archived" tone="neutral" />}
                        {hasReceipts ? (
                          <Pill label="Bank receipts ✓" tone="positive" />
                        ) : (
                          <Pill label="No bank receipts" tone="neutral" />
                        )}
                        {!first && (
                          <span className="rounded bg-secondary/80 px-1.5 py-0.2 text-[10px] font-medium text-muted-foreground">
                            Earlier Snapshot
                          </span>
                        )}
                      </p>
                      <p className="mt-1 text-xs text-muted-foreground">
                        {s.source_type.replace("_", " ")} · {s.coverage.length} collections · imported by {s.imported_by}{" "}
                        {formatDateTime(s.imported_at)} · sha256 <span className="font-mono">{shortHash(s.sha256)}</span>
                        {s.parent_id && " · extends earlier snapshot"}
                        {s.used_by_cases > 0 && (
                          <span className="font-semibold text-foreground"> · {s.used_by_cases} case(s) bound</span>
                        )}
                      </p>
                    </div>
                    <div className="flex shrink-0 items-center gap-1 text-xs text-muted-foreground pt-1">
                      <span>{isOpen ? "Hide" : "Details"}</span>
                      {isOpen ? <ChevronDown className="h-4 w-4" /> : <ChevronRight className="h-4 w-4" />}
                    </div>
                  </button>
                  {isOpen && (
                    <div className="mt-2 space-y-4 rounded-md border border-border/80 bg-secondary/20 p-3 shadow-2xs">
                      <p className="text-xs font-mono break-all text-muted-foreground">Source: {s.source_reference}</p>
                      <Rows snapshot={s} />
                      {!s.archived && <BankStatement snapshot={s} />}
                      <Removal snapshot={s} />
                    </div>
                  )}
                  {first && older.length > 0 && (
                    <div className="mt-1 pl-2.5">
                      <button
                        type="button"
                        className="inline-flex items-center gap-1.5 rounded-full border border-border/70 bg-card px-2.5 py-1 text-xs font-medium text-foreground transition-all hover:border-primary/40 hover:bg-secondary/60 hover:text-primary shadow-2xs"
                        onClick={() =>
                          setExpanded((prev) => {
                            const next = new Set(prev)
                            if (next.has(key)) next.delete(key)
                            else next.add(key)
                            return next
                          })
                        }
                      >
                        <History className="size-3 text-muted-foreground" />
                        <span>
                          {expanded.has(key)
                            ? `Hide ${older.length} earlier snapshot${older.length > 1 ? "s" : ""}`
                            : `Show ${older.length} earlier snapshot${older.length > 1 ? "s" : ""} of ${s.company_name}`}
                        </span>
                        {expanded.has(key) ? <ChevronDown className="size-3" /> : <ChevronRight className="size-3" />}
                      </button>
                    </div>
                  )}
                </li>
              )
            })}
          </ul>
        </Card>
        <div className="space-y-6">
          <Card
            title="Attach bank statement (CSV)"
            hint="Upload bank statement receipts to run bank-to-invoice reconciliation"
          >
            <BankStatementImport snapshots={snapshots.data ?? []} />
          </Card>
          <Card title="Import an export">
            <JsonImport />
          </Card>
          <Card title="From QuickBooks Online">
            <QuickBooksImport />
          </Card>
        </div>
      </div>
    </PodPage>
  )
}
