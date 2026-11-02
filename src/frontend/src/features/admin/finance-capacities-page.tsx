import { useState, type FormEvent } from "react"
import { LoaderCircle, Plus, Trash2 } from "lucide-react"
import { toast } from "sonner"

import { AppPage } from "@/components/layout/app-page"
import { Alert } from "@/components/ui/alert"
import { Button } from "@/components/ui/button"
import { Label } from "@/components/ui/label"
import { Panel } from "@/features/agent-catalog/workspace/components/panel"
import { useEntities } from "@/features/entities/hooks"
import type { Assignment, FinanceCapacity } from "@/features/finance-pod/api"
import { useAssignments, useCapacityCatalog, useGrant, useRevoke } from "@/features/finance-pod/hooks"
import { selectClass } from "@/features/service-pod/ui"
import { errorMessage } from "@/lib/api"

import { AdminTabs } from "./components/admin-tabs"
import { useUsers } from "./hooks"

function GrantForm() {
  const users = useUsers("")
  const entities = useEntities()
  const catalog = useCapacityCatalog()
  const grant = useGrant()
  const [userId, setUserId] = useState("")
  const [capacity, setCapacity] = useState<FinanceCapacity | "">("")
  const [entityId, setEntityId] = useState("")
  const described = catalog.data?.find((c) => c.key === capacity)

  const onSubmit = (e: FormEvent) => {
    e.preventDefault()
    if (!userId || !capacity) return
    grant.mutate(
      { user_id: userId, capacity, entity_id: entityId || null },
      {
        onSuccess: (a) => {
          toast.success(`${a.label} granted to ${a.user.name}`)
          setCapacity("")
        },
      },
    )
  }

  return (
    <form onSubmit={onSubmit} className="space-y-3" aria-label="Grant a capacity">
      {grant.error && <Alert>{errorMessage(grant.error, "Couldn't grant the capacity.")}</Alert>}
      <div className="grid gap-3 sm:grid-cols-[minmax(0,1fr)_220px_180px_auto] sm:items-end">
        <div className="space-y-1.5">
          <Label htmlFor="cap-user">Person</Label>
          <select id="cap-user" className={selectClass} value={userId} onChange={(e) => setUserId(e.target.value)} required>
            <option value="">Choose…</option>
            {users.data
              ?.filter((u) => u.is_active)
              .map((u) => (
                <option key={u.id} value={u.id}>
                  {u.full_name} · {u.email}
                </option>
              ))}
          </select>
        </div>
        <div className="space-y-1.5">
          <Label htmlFor="cap-capacity">Capacity</Label>
          <select
            id="cap-capacity"
            className={selectClass}
            value={capacity}
            onChange={(e) => setCapacity(e.target.value as FinanceCapacity)}
            required
          >
            <option value="">Choose…</option>
            {catalog.data?.map((c) => (
              <option key={c.key} value={c.key}>
                {c.label}
              </option>
            ))}
          </select>
        </div>
        <div className="space-y-1.5">
          <Label htmlFor="cap-entity">For</Label>
          <select id="cap-entity" className={selectClass} value={entityId} onChange={(e) => setEntityId(e.target.value)}>
            <option value="">All entities</option>
            {entities.data
              ?.filter((en) => en.is_active)
              .map((en) => (
                <option key={en.id} value={en.id}>
                  {en.code} · {en.name}
                </option>
              ))}
          </select>
        </div>
        <Button type="submit" disabled={grant.isPending}>
          {grant.isPending ? <LoaderCircle className="animate-spin" aria-hidden /> : <Plus aria-hidden />}
          Grant
        </Button>
      </div>
      <p className="text-xs text-muted-foreground">
        {described?.description ??
          "Capacities decide who completes which Finance POD step. Finance Admins hold all of them, but nobody approves their own work where a second person is required."}
      </p>
    </form>
  )
}

function AssignmentRow({ a }: { a: Assignment }) {
  const revoke = useRevoke()
  const [confirming, setConfirming] = useState(false)
  return (
    <tr>
      <td className="py-3 pr-4">
        <span className="font-medium">{a.user.name}</span>
        <span className="block text-xs text-muted-foreground">{a.user.email}</span>
      </td>
      <td className="py-3 pr-4">{a.label}</td>
      <td className="py-3 pr-4">{a.entity ? `${a.entity.code} · ${a.entity.name}` : "All entities"}</td>
      <td className="py-3 pr-4 text-xs text-muted-foreground">
        {a.granted_by ?? "—"} · {new Date(a.created_at).toLocaleDateString()}
      </td>
      <td className="py-3 text-right">
        {confirming ? (
          <span className="inline-flex gap-2">
            <Button
              size="sm"
              variant="destructive"
              disabled={revoke.isPending}
              onClick={() =>
                revoke.mutate(a.id, {
                  onSuccess: () => toast.success(`${a.label} revoked from ${a.user.name}`),
                  onError: (error) => toast.error(errorMessage(error, "Couldn't revoke.")),
                })
              }
            >
              Revoke
            </Button>
            <Button size="sm" variant="ghost" onClick={() => setConfirming(false)}>
              Keep
            </Button>
          </span>
        ) : (
          <button
            type="button"
            className="rounded p-1.5 text-muted-foreground hover:bg-secondary hover:text-foreground"
            onClick={() => setConfirming(true)}
            aria-label={`Revoke ${a.label} from ${a.user.name}`}
          >
            <Trash2 className="size-4" aria-hidden />
          </button>
        )}
      </td>
    </tr>
  )
}

export function FinanceCapacitiesPage() {
  const { data, isLoading, isError } = useAssignments()
  return (
    <AppPage title="Admin Settings" subtitle="Who holds which Finance POD capacity.">
      <AdminTabs />
      <div className="space-y-6">
        <Panel title="Grant a capacity">
          <GrantForm />
        </Panel>
        <Panel title="Finance POD capacities">
          {isLoading && <p className="text-sm text-muted-foreground">Loading…</p>}
          {isError && <Alert>Couldn't load the capacities.</Alert>}
          {data && data.length === 0 && <p className="text-sm text-muted-foreground">Nobody holds a capacity yet.</p>}
          {data && data.length > 0 && (
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead className="text-left text-xs text-muted-foreground">
                  <tr>
                    <th className="pb-2 pr-4 font-medium">Person</th>
                    <th className="pb-2 pr-4 font-medium">Capacity</th>
                    <th className="pb-2 pr-4 font-medium">For</th>
                    <th className="pb-2 pr-4 font-medium">Granted by</th>
                    <th className="pb-2" />
                  </tr>
                </thead>
                <tbody className="divide-y">
                  {data.map((a) => (
                    <AssignmentRow key={a.id} a={a} />
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </Panel>
      </div>
    </AppPage>
  )
}
