import { Link } from "react-router"
import { LoaderCircle } from "lucide-react"

import { Alert } from "@/components/ui/alert"
import { useEntities } from "@/features/entities/hooks"

interface EntitiesEditorProps {
  value: string[]
  onChange: (value: string[]) => void
  disabled?: boolean
}

/** Which legal entities a user files runs for (and sees runs of). */
export function EntitiesEditor({ value, onChange, disabled }: EntitiesEditorProps) {
  const { data: entities, isPending, isError } = useEntities()

  if (isPending) return <LoaderCircle className="size-4 animate-spin text-primary" aria-label="Loading" />
  if (isError) return <Alert>Couldn't load legal entities.</Alert>
  if (!entities.length) {
    return (
      <p className="text-sm text-muted-foreground">
        No legal entities yet.{" "}
        <Link to="/admin/entities" className="font-medium text-primary hover:underline">
          Add one
        </Link>{" "}
        to scope runs by entity.
      </p>
    )
  }

  const toggle = (id: string, checked: boolean) =>
    onChange(checked ? [...value, id] : value.filter((v) => v !== id))

  return (
    <div className="grid gap-2 sm:grid-cols-2">
      {entities.map((e) => (
        <label key={e.id} className="flex items-center gap-2.5 rounded-md border px-3 py-2 text-sm">
          <input
            type="checkbox"
            className="size-4 accent-primary"
            checked={value.includes(e.id)}
            onChange={(ev) => toggle(e.id, ev.target.checked)}
            disabled={disabled}
          />
          <span className="font-mono text-xs font-semibold">{e.code}</span>
          <span className="truncate">{e.name}</span>
          {!e.is_active && <span className="text-xs text-muted-foreground">(inactive)</span>}
        </label>
      ))}
    </div>
  )
}
