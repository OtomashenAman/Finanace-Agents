import { useState, type FormEvent } from "react"
import { LoaderCircle, Pencil, Plus } from "lucide-react"
import { toast } from "sonner"

import { AppPage } from "@/components/layout/app-page"
import { Alert } from "@/components/ui/alert"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Switch } from "@/components/ui/switch"
import { Panel } from "@/features/agent-catalog/workspace/components/panel"
import type { LegalEntity } from "@/features/entities/api"
import { useCreateEntity, useEntities, useUpdateEntity } from "@/features/entities/hooks"
import { errorMessage } from "@/lib/api"

import { AdminTabs } from "./components/admin-tabs"

function CreateEntityForm() {
  const create = useCreateEntity()
  const [code, setCode] = useState("")
  const [name, setName] = useState("")

  const onSubmit = (e: FormEvent) => {
    e.preventDefault()
    if (!code.trim() || !name.trim()) return
    create.mutate(
      { code: code.trim(), name: name.trim() },
      {
        onSuccess: (entity) => {
          toast.success(`${entity.code} created`, { description: "Assign it to users under Users." })
          setCode("")
          setName("")
        },
      },
    )
  }

  return (
    <form onSubmit={onSubmit} className="space-y-3" aria-label="New legal entity">
      {create.error && <Alert>{errorMessage(create.error, "Couldn't create the entity.")}</Alert>}
      <div className="grid gap-3 sm:grid-cols-[160px_minmax(0,1fr)_auto] sm:items-end">
        <div className="space-y-1.5">
          <Label htmlFor="entity-code">Code</Label>
          <Input
            id="entity-code"
            className="h-10 uppercase"
            value={code}
            onChange={(e) => setCode(e.target.value)}
            placeholder="US01"
            maxLength={20}
            pattern="[A-Za-z0-9_-]+"
            title="Letters, digits, - and _"
            required
          />
        </div>
        <div className="space-y-1.5">
          <Label htmlFor="entity-name">Name</Label>
          <Input
            id="entity-name"
            className="h-10"
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder="US Operations"
            maxLength={200}
            required
          />
        </div>
        <Button type="submit" disabled={create.isPending}>
          {create.isPending ? <LoaderCircle className="animate-spin" aria-hidden /> : <Plus aria-hidden />}
          Add entity
        </Button>
      </div>
      <p className="text-xs text-muted-foreground">The code can't change later. Entities are never deleted, only deactivated.</p>
    </form>
  )
}

function EntityRow({ entity }: { entity: LegalEntity }) {
  const update = useUpdateEntity()
  const [editing, setEditing] = useState(false)
  const [name, setName] = useState(entity.name)

  const save = (patch: { name?: string; is_active?: boolean }, done?: () => void) =>
    update.mutate(
      { id: entity.id, ...patch },
      {
        onSuccess: () => done?.(),
        onError: (error) => toast.error(errorMessage(error, "Couldn't update the entity")),
      },
    )

  return (
    <tr>
      <td className="py-3 pr-4 font-mono text-sm font-semibold">{entity.code}</td>
      <td className="py-3 pr-4">
        {editing ? (
          <form
            className="flex gap-2"
            onSubmit={(e) => {
              e.preventDefault()
              if (name.trim()) save({ name: name.trim() }, () => setEditing(false))
            }}
          >
            <Input value={name} onChange={(e) => setName(e.target.value)} maxLength={200} className="h-9" aria-label="Name" autoFocus />
            <Button type="submit" size="sm" disabled={update.isPending}>
              Save
            </Button>
            <Button type="button" size="sm" variant="ghost" onClick={() => setEditing(false)}>
              Cancel
            </Button>
          </form>
        ) : (
          <span className="flex items-center gap-2">
            {entity.name}
            <button
              type="button"
              className="rounded p-1 text-muted-foreground hover:bg-secondary hover:text-foreground"
              onClick={() => setEditing(true)}
              aria-label={`Rename ${entity.code}`}
            >
              <Pencil className="size-3.5" />
            </button>
          </span>
        )}
      </td>
      <td className="py-3">
        <label className="flex items-center gap-2.5 text-sm">
          <Switch
            checked={entity.is_active}
            onCheckedChange={(active) => save({ is_active: active })}
            disabled={update.isPending}
            aria-label={`${entity.is_active ? "Deactivate" : "Activate"} ${entity.code}`}
          />
          {entity.is_active ? "Active" : "Inactive"}
        </label>
      </td>
    </tr>
  )
}

/** Legal entities runs are filed for; users only see runs of the entities they work for. */
export function EntitiesPage() {
  const { data: entities, isPending, isError } = useEntities()

  return (
    <AppPage
      title="Admin Settings · Legal entities"
      subtitle="Each run is filed for one legal entity. Users only start and see runs for the entities assigned to them."
    >
      <AdminTabs />
      <div className="grid items-start gap-6 xl:grid-cols-[minmax(0,1fr)_minmax(0,1fr)]">
        <Panel title="Entities">
          {isPending && <LoaderCircle className="size-5 animate-spin text-primary" aria-label="Loading" />}
          {isError && <Alert>Couldn't load legal entities.</Alert>}
          {entities?.length === 0 && (
            <p className="text-sm text-muted-foreground">
              No entities yet: runs aren't tied to an entity. Add the first one to switch on entity scoping.
            </p>
          )}
          {entities && entities.length > 0 && (
            <div className="overflow-x-auto">
              <table className="w-full min-w-[420px] text-sm">
                <thead>
                  <tr className="border-b text-left text-xs tracking-wide text-muted-foreground uppercase">
                    <th className="py-2 pr-4 font-semibold">Code</th>
                    <th className="py-2 pr-4 font-semibold">Name</th>
                    <th className="py-2 font-semibold">Status</th>
                  </tr>
                </thead>
                <tbody className="divide-y">
                  {entities.map((e) => (
                    <EntityRow key={e.id} entity={e} />
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </Panel>
        <Panel title="New entity">
          <CreateEntityForm />
        </Panel>
      </div>
    </AppPage>
  )
}
