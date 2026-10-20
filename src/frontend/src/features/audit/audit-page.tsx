import { Fragment, useState } from "react"
import { Link } from "react-router"
import { ChevronDown, ChevronRight, Download, Inbox, LoaderCircle, ShieldAlert, ShieldCheck } from "lucide-react"
import { toast } from "sonner"

import { AppPage } from "@/components/layout/app-page"
import { Alert } from "@/components/ui/alert"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { useUsers } from "@/features/admin/hooks"
import { formatDateTime } from "@/features/agent-catalog/workspace/format"
import { useCurrentUser } from "@/features/auth/hooks"
import { isAdmin } from "@/features/auth/roles"
import { errorMessage } from "@/lib/api"
import { cn } from "@/lib/utils"

import { CATEGORY_LABELS, type AuditCategory, type AuditFilters } from "./api"
import { EventDetails } from "./components/event-details"
import { useAuditEvents, useAuditIntegrity, useExportAudit } from "./hooks"

const FIELD =
  "flex h-10 w-full rounded-md border border-input bg-background px-3 text-sm focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/20 focus-visible:outline-none"

function Filters({
  value,
  onChange,
  admin,
}: {
  value: AuditFilters
  onChange: (next: AuditFilters) => void
  admin: boolean
}) {
  const users = useUsers("", admin)
  const set = (patch: Partial<AuditFilters>) => onChange({ ...value, ...patch })

  return (
    <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-6">
      <div className="space-y-1.5 lg:col-span-2">
        <Label htmlFor="f-category" className="text-xs">
          Category
        </Label>
        <select
          id="f-category"
          className={FIELD}
          value={value.category ?? ""}
          onChange={(e) => set({ category: (e.target.value || undefined) as AuditCategory | undefined })}
        >
          <option value="">All</option>
          {(Object.keys(CATEGORY_LABELS) as AuditCategory[])
            .filter((c) => admin || c !== "audit")
            .map((c) => (
              <option key={c} value={c}>
                {CATEGORY_LABELS[c]}
              </option>
            ))}
        </select>
      </div>
      {admin && (
        <div className="space-y-1.5 lg:col-span-2">
          <Label htmlFor="f-actor" className="text-xs">
            Done by
          </Label>
          <select
            id="f-actor"
            className={FIELD}
            value={value.actorId ?? ""}
            onChange={(e) => set({ actorId: e.target.value || undefined })}
          >
            <option value="">Anyone</option>
            {users.data?.map((u) => (
              <option key={u.id} value={u.id}>
                {u.full_name} ({u.email})
              </option>
            ))}
          </select>
        </div>
      )}
      <div className="space-y-1.5">
        <Label htmlFor="f-run" className="text-xs">
          Run
        </Label>
        <Input
          id="f-run"
          className="h-10 text-sm"
          placeholder="RUN-01006"
          value={value.run ?? ""}
          onChange={(e) => set({ run: e.target.value.trim() || undefined })}
        />
      </div>
      <div className="space-y-1.5">
        <Label htmlFor="f-since" className="text-xs">
          From
        </Label>
        <Input
          id="f-since"
          type="date"
          className="h-10 text-sm"
          value={value.since ?? ""}
          onChange={(e) => set({ since: e.target.value || undefined })}
        />
      </div>
      <div className="space-y-1.5">
        <Label htmlFor="f-until" className="text-xs">
          To
        </Label>
        <Input
          id="f-until"
          type="date"
          className="h-10 text-sm"
          value={value.until ?? ""}
          onChange={(e) => set({ until: e.target.value || undefined })}
        />
      </div>
      <label className="flex items-center gap-2 self-end pb-2.5 text-sm">
        <input
          type="checkbox"
          className="size-4 accent-primary"
          checked={value.failuresOnly ?? false}
          onChange={(e) => set({ failuresOnly: e.target.checked || undefined })}
        />
        Failures &amp; security only
      </label>
    </div>
  )
}

/** Read-only history of who did what. Admin: everyone; user: their own activity. */
export function AuditPage() {
  const { data: user } = useCurrentUser()
  const admin = isAdmin(user)
  const [filters, setFilters] = useState<AuditFilters>({})
  const [open, setOpen] = useState<string | null>(null)
  const events = useAuditEvents(filters)
  const exportCsv = useExportAudit()
  const integrity = useAuditIntegrity(admin)
  const rows = events.data?.pages.flatMap((p) => p.items) ?? []

  const onExport = () =>
    exportCsv.mutate(filters, {
      onSuccess: () => toast.success("Audit trail exported"),
      onError: (error) => toast.error(errorMessage(error, "Couldn't export the audit trail")),
    })

  return (
    <AppPage
      title="Audit Trail"
      subtitle={
        admin
          ? "Every sign-in, user change, run, approval and data source action. Read-only: nothing here can be edited or deleted."
          : "Your own activity, changes made to your account and everything that happened on your runs."
      }
    >
      {admin && integrity.data && (
        <div
          className={cn(
            "mb-4 flex flex-wrap items-center justify-between gap-3 rounded-md border px-4 py-3 text-sm",
            integrity.data.valid ? "border-emerald-200 bg-emerald-50 text-emerald-900" : "border-red-200 bg-red-50 text-red-900",
          )}
          role="status"
        >
          <span className="flex items-center gap-2">
            {integrity.data.valid ? <ShieldCheck className="size-4" aria-hidden /> : <ShieldAlert className="size-4" aria-hidden />}
            {integrity.data.valid
              ? `Tamper check passed: all ${integrity.data.checked.toLocaleString()} events chain correctly.`
              : `Tamper check FAILED at event #${integrity.data.first_broken_seq}: the trail was changed outside the app.`}
            <span className="text-xs opacity-75">
              Kept {Math.round(integrity.data.retention_days / 365)} years · checked {formatDateTime(integrity.data.checked_at)}
            </span>
          </span>
          <Button type="button" size="sm" variant="outline" onClick={() => void integrity.refetch()} disabled={integrity.isFetching}>
            {integrity.isFetching && <LoaderCircle className="animate-spin" aria-hidden />}
            Verify again
          </Button>
        </div>
      )}
      <section className="space-y-5 rounded-lg border bg-card p-5 sm:p-6">
        <div className="flex flex-wrap items-end justify-between gap-4">
          <div className="min-w-0 flex-1">
            <Filters value={filters} onChange={setFilters} admin={admin} />
          </div>
          {admin && (
            <Button type="button" variant="outline" onClick={onExport} disabled={exportCsv.isPending}>
              {exportCsv.isPending ? <LoaderCircle className="animate-spin" aria-hidden /> : <Download aria-hidden />}
              Export CSV
            </Button>
          )}
        </div>

        {events.isPending && (
          <div className="flex justify-center py-12" role="status">
            <LoaderCircle className="size-6 animate-spin text-primary" aria-hidden />
            <span className="sr-only">Loading audit trail…</span>
          </div>
        )}
        {events.isError && <Alert>{errorMessage(events.error, "Couldn't load the audit trail.")}</Alert>}
        {events.data && rows.length === 0 && (
          <div className="flex flex-col items-center gap-2 py-12 text-center">
            <Inbox className="size-7 text-muted-foreground" aria-hidden />
            <p className="font-medium">No events match these filters</p>
          </div>
        )}

        {rows.length > 0 && (
          <div className="overflow-x-auto">
            <table className="w-full min-w-[720px] text-sm">
              <thead>
                <tr className="border-b text-left text-xs tracking-wide text-muted-foreground uppercase">
                  <th className="w-8 py-2" aria-label="Details" />
                  <th className="py-2 pr-4 font-semibold">Time</th>
                  <th className="py-2 pr-4 font-semibold">Who</th>
                  <th className="py-2 pr-4 font-semibold">What happened</th>
                  <th className="py-2 pr-4 font-semibold">Category</th>
                  <th className="py-2 font-semibold">Run</th>
                </tr>
              </thead>
              <tbody className="divide-y">
                {rows.map((e) => {
                  const expanded = open === e.id
                  return (
                    <Fragment key={e.id}>
                      <tr
                        className={cn("cursor-pointer hover:bg-secondary/40", expanded && "bg-secondary/40")}
                        onClick={() => setOpen(expanded ? null : e.id)}
                      >
                        <td className="py-3 pl-1">
                          <button
                            type="button"
                            aria-expanded={expanded}
                            aria-label={expanded ? "Hide details" : "Show details"}
                            className="text-muted-foreground"
                            onClick={(ev) => {
                              ev.stopPropagation()
                              setOpen(expanded ? null : e.id)
                            }}
                          >
                            {expanded ? <ChevronDown className="size-4" /> : <ChevronRight className="size-4" />}
                          </button>
                        </td>
                        <td className="py-3 pr-4 whitespace-nowrap text-muted-foreground">{formatDateTime(e.created_at)}</td>
                        <td className="py-3 pr-4">{e.actor?.full_name ?? <span className="text-muted-foreground">—</span>}</td>
                        <td className={cn("py-3 pr-4", e.outcome === "failure" && "font-medium text-red-800")}>
                          {e.summary}
                        </td>
                        <td className="py-3 pr-4 text-muted-foreground">
                          {e.category ? CATEGORY_LABELS[e.category] : "—"}
                        </td>
                        <td className="py-3">
                          {e.run ? (
                            <Link
                              to={`/catalog/${e.run.agent_key}/runs/${e.run.id}`}
                              className="font-medium text-primary hover:underline"
                              onClick={(ev) => ev.stopPropagation()}
                            >
                              {e.run.reference}
                            </Link>
                          ) : (
                            <span className="text-muted-foreground">{String(e.details.run ?? "—")}</span>
                          )}
                        </td>
                      </tr>
                      {expanded && (
                        <tr>
                          <td colSpan={6} className="pb-4">
                            <EventDetails event={e} />
                          </td>
                        </tr>
                      )}
                    </Fragment>
                  )
                })}
              </tbody>
            </table>
          </div>
        )}

        {events.hasNextPage && (
          <div className="flex justify-center">
            <Button
              type="button"
              variant="outline"
              onClick={() => void events.fetchNextPage()}
              disabled={events.isFetchingNextPage}
            >
              {events.isFetchingNextPage && <LoaderCircle className="animate-spin" aria-hidden />}
              Load older events
            </Button>
          </div>
        )}
      </section>
    </AppPage>
  )
}
