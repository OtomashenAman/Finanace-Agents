import { useState } from "react"
import { FileSpreadsheet, KeyRound, Landmark, LoaderCircle, Pencil, RefreshCw, Settings2, Trash2 } from "lucide-react"
import { toast } from "sonner"

import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { formatDateTime } from "@/features/agent-catalog/workspace/format"
import { errorMessage } from "@/lib/api"
import { cn } from "@/lib/utils"

import type { DataSource, RecordType } from "../api"
import { useAuthorizeQuickBooks, useDeleteSource, useRenameSource, useSyncSource } from "../hooks"
import { RECORD_LABELS, STATUS } from "../labels"
import { QuickBooksAppForm } from "./quickbooks-app-form"

export function StatusPill({ source }: { source: DataSource }) {
  const { label, tone } = STATUS[source.status]
  return <span className={cn("rounded px-2 py-0.5 text-xs font-medium whitespace-nowrap", tone)}>{label}</span>
}

function RenameForm({ source, onDone }: { source: DataSource; onDone: () => void }) {
  const rename = useRenameSource()
  const [name, setName] = useState(source.name)
  return (
    <form
      className="flex gap-2"
      onSubmit={(e) => {
        e.preventDefault()
        if (!name.trim()) return
        rename.mutate(
          { id: source.id, name: name.trim() },
          { onSuccess: onDone, onError: (error) => toast.error(errorMessage(error, "Couldn't rename")) },
        )
      }}
    >
      <Input value={name} onChange={(e) => setName(e.target.value)} maxLength={200} aria-label="Name" autoFocus className="h-9" />
      <Button type="submit" size="sm" disabled={rename.isPending}>
        Save
      </Button>
      <Button type="button" size="sm" variant="ghost" onClick={onDone}>
        Cancel
      </Button>
    </form>
  )
}

export function SourceCard({ source }: { source: DataSource }) {
  const sync = useSyncSource()
  const authorize = useAuthorizeQuickBooks()
  const remove = useDeleteSource()
  const [renaming, setRenaming] = useState(false)
  const [editingApp, setEditingApp] = useState(false)
  const [confirmingDelete, setConfirmingDelete] = useState(false)

  const isQuickBooks = source.kind === "quickbooks"
  const needsAuth = source.status === "needs_reauth" || source.status === "pending_auth"
  const counts = (Object.entries(source.record_counts) as [RecordType, number][]).filter(([, n]) => n > 0)
  const Icon = isQuickBooks ? Landmark : FileSpreadsheet

  const onSync = () =>
    sync.mutate(source.id, {
      onSuccess: () => toast.success(`${source.name} synced`),
      onError: (error) => toast.error(errorMessage(error, "Sync failed")),
    })

  const onAuthorize = () =>
    authorize.mutate(source.id, { onError: (error) => toast.error(errorMessage(error, "Couldn't start authorization")) })

  const onDelete = () =>
    remove.mutate(source.id, {
      onSuccess: () => toast.success(isQuickBooks ? `${source.name} disconnected` : `${source.name} removed`),
      onError: (error) => toast.error(errorMessage(error, "Couldn't remove the data source")),
      onSettled: () => setConfirmingDelete(false),
    })

  return (
    <article className="flex flex-col rounded-lg border bg-card p-5" aria-label={source.name}>
      <div className="flex items-start gap-3">
        <span className="flex size-9 shrink-0 items-center justify-center rounded-md bg-secondary text-brand-navy" aria-hidden>
          <Icon className="size-4" />
        </span>
        <div className="min-w-0 flex-1">
          {renaming ? (
            <RenameForm source={source} onDone={() => setRenaming(false)} />
          ) : (
            <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
              <h2 className="truncate text-[15px] font-semibold text-brand-navy" title={source.name}>
                {source.name}
              </h2>
              <StatusPill source={source} />
            </div>
          )}
          <p className="mt-0.5 text-xs text-muted-foreground">
            {isQuickBooks
              ? [
                  "QuickBooks Online",
                  source.environment === "sandbox" && "sandbox",
                  source.external_id && `company ${source.external_id}`,
                ]
                  .filter(Boolean)
                  .join(" · ")
              : `Upload · ${source.filename ?? "file"}`}
          </p>
        </div>
      </div>

      {counts.length > 0 && (
        <ul className="mt-4 flex flex-wrap gap-2 text-xs">
          {counts.map(([type, n]) => (
            <li key={type} className="rounded bg-secondary px-2 py-1">
              <span className="font-semibold">{n.toLocaleString()}</span> {RECORD_LABELS[type].toLowerCase()}
            </li>
          ))}
        </ul>
      )}

      {source.last_error && (
        <p className={cn("mt-3 text-sm", source.status === "connected" ? "text-muted-foreground" : "text-destructive")}>
          {source.last_error}
        </p>
      )}

      {editingApp && (
        <div className="mt-4 border-t pt-4">
          <QuickBooksAppForm source={source} onDone={() => setEditingApp(false)} />
        </div>
      )}

      <p className="mt-3 text-xs text-muted-foreground">
        {isQuickBooks ? "Last synced" : "Imported"}: {source.last_synced_at ? formatDateTime(source.last_synced_at) : "never"}
      </p>

      <div className="mt-auto flex flex-wrap gap-2 pt-4">
        {isQuickBooks && !needsAuth && (
          <Button type="button" size="sm" variant="outline" onClick={onSync} disabled={sync.isPending}>
            {sync.isPending ? <LoaderCircle className="animate-spin" aria-hidden /> : <RefreshCw aria-hidden />}
            {sync.isPending ? "Syncing…" : "Sync now"}
          </Button>
        )}
        {isQuickBooks && (
          <Button
            type="button"
            size="sm"
            variant={needsAuth ? "default" : "ghost"}
            onClick={onAuthorize}
            disabled={authorize.isPending}
          >
            <KeyRound aria-hidden />
            {source.status === "pending_auth" ? "Authorize" : "Re-authorize"}
          </Button>
        )}
        {isQuickBooks && !editingApp && (
          <Button
            type="button"
            size="sm"
            variant="ghost"
            onClick={() => setEditingApp(true)}
            aria-label={`App credentials for ${source.name}`}
            title="App credentials"
          >
            <Settings2 aria-hidden />
          </Button>
        )}
        {!renaming && (
          <Button type="button" size="sm" variant="ghost" onClick={() => setRenaming(true)} aria-label={`Rename ${source.name}`}>
            <Pencil aria-hidden />
          </Button>
        )}
        {confirmingDelete ? (
          <span className="flex gap-2">
            <Button type="button" size="sm" variant="destructive" onClick={onDelete} disabled={remove.isPending}>
              {isQuickBooks ? "Yes, disconnect" : "Yes, remove"}
            </Button>
            <Button type="button" size="sm" variant="ghost" onClick={() => setConfirmingDelete(false)}>
              Cancel
            </Button>
          </span>
        ) : (
          <Button
            type="button"
            size="sm"
            variant="ghost"
            onClick={() => setConfirmingDelete(true)}
            aria-label={isQuickBooks ? `Disconnect ${source.name}` : `Remove ${source.name}`}
          >
            <Trash2 aria-hidden />
          </Button>
        )}
      </div>
    </article>
  )
}
