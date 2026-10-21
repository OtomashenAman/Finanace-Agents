import { useState, type FormEvent } from "react"
import { History, LoaderCircle, Plus, X } from "lucide-react"
import { toast } from "sonner"

import { Alert } from "@/components/ui/alert"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { formatDateTime, parseMoneyInput } from "@/features/agent-catalog/workspace/format"
import { ApiError, errorMessage } from "@/lib/api"

import type { Policy } from "../api"
import { usePolicyHistory, useSavePolicy } from "../hooks"

type MapRow = { name: string; amount: string }
type PolicyValue = string | Record<string, string> | null | undefined

const isMap = (f: Policy["fields"][number]) => f.kind === "money_map"

function initial(policy: Policy): Record<string, string> {
  return Object.fromEntries(
    policy.fields.filter((f) => !isMap(f)).map((f) => [f.name, String(policy.current.values[f.name] ?? "")]),
  )
}

function initialMaps(policy: Policy): Record<string, MapRow[]> {
  return Object.fromEntries(
    policy.fields.filter(isMap).map((f) => {
      const value = (policy.current.values[f.name] ?? {}) as Record<string, string>
      return [f.name, Object.entries(value).map(([name, amount]) => ({ name, amount: String(amount) }))]
    }),
  )
}

/** "Meals 75.00, Lodging 200.00" for a money map, the value or "off" otherwise */
function describe(value: PolicyValue): string {
  if (value === null || value === undefined) return "off"
  if (typeof value === "object") {
    const entries = Object.entries(value)
    return entries.length ? entries.map(([k, v]) => `${k} ${v}`).join(", ") : "none"
  }
  return value
}

/** Name -> amount rows, e.g. an expense limit per category */
function MoneyMapEditor({
  id,
  rows,
  onChange,
}: {
  id: string
  rows: MapRow[]
  onChange: (rows: MapRow[]) => void
}) {
  const update = (index: number, patch: Partial<MapRow>) =>
    onChange(rows.map((row, i) => (i === index ? { ...row, ...patch } : row)))
  return (
    <div className="space-y-2">
      {rows.map((row, index) => (
        <div key={index} className="flex gap-2">
          <Input
            aria-label={`Name ${index + 1}`}
            id={index === 0 ? id : undefined}
            className="h-10 min-w-0 flex-1 text-sm"
            value={row.name}
            placeholder="e.g. Meals"
            onChange={(e) => update(index, { name: e.target.value })}
          />
          <Input
            aria-label={`Amount ${index + 1}`}
            inputMode="decimal"
            className="h-10 w-32 text-sm"
            value={row.amount}
            placeholder="0.00"
            onChange={(e) => update(index, { amount: e.target.value })}
          />
          <Button
            type="button"
            size="icon"
            variant="ghost"
            aria-label={`Remove ${row.name || `row ${index + 1}`}`}
            onClick={() => onChange(rows.filter((_, i) => i !== index))}
          >
            <X aria-hidden />
          </Button>
        </div>
      ))}
      <Button type="button" size="sm" variant="outline" onClick={() => onChange([...rows, { name: "", amount: "" }])}>
        <Plus aria-hidden />
        Add
      </Button>
    </div>
  )
}

function VersionList({ policy }: { policy: Policy }) {
  const { data, isPending } = usePolicyHistory(policy.agent_key, true)
  if (isPending) return <LoaderCircle className="size-4 animate-spin text-primary" aria-label="Loading" />
  return (
    <ol className="space-y-2 text-sm">
      {data?.map((v) => (
        <li key={v.version_label} className="rounded-md border bg-background p-3">
          <p className="font-semibold">
            {v.version_label}
            {v.version_label === policy.current.version_label && (
              <span className="ml-2 rounded bg-emerald-50 px-1.5 py-0.5 text-xs font-medium text-emerald-800">in force</span>
            )}
          </p>
          <p className="text-xs text-muted-foreground">
            {v.is_default ? "Code defaults" : `${v.created_by ?? "Deleted user"} · ${formatDateTime(v.created_at)}`}
            {v.note && ` · ${v.note}`}
          </p>
          <p className="mt-1 font-mono text-xs break-all text-muted-foreground">
            {policy.fields.map((f) => `${f.name}=${describe(v.values[f.name] as PolicyValue)}`).join("  ")}
          </p>
        </li>
      ))}
    </ol>
  )
}

/** An agent's thresholds; saving creates a new version used by analyses from then on. */
export function PolicyCard({ policy }: { policy: Policy }) {
  const save = useSavePolicy()
  const [values, setValues] = useState(() => initial(policy))
  const [maps, setMaps] = useState(() => initialMaps(policy))
  const [note, setNote] = useState("")
  const [showHistory, setShowHistory] = useState(false)
  const fieldErrors = save.error instanceof ApiError ? save.error.fieldErrors : {}
  // A money map's errors are keyed by the row's name, not the field's
  const mapError = Object.entries(fieldErrors).find(([key]) => !(key in values))?.[1]

  const onSubmit = (e: FormEvent) => {
    e.preventDefault()
    const payload: Record<string, unknown> = Object.fromEntries(
      Object.entries(values).map(([k, v]) => [k, v.trim() ? parseMoneyInput(v.trim()) : null]),
    )
    for (const [name, rows] of Object.entries(maps)) {
      payload[name] = Object.fromEntries(
        rows.filter((r) => r.name.trim() || r.amount.trim()).map((r) => [r.name.trim(), parseMoneyInput(r.amount.trim())]),
      )
    }
    save.mutate(
      { key: policy.agent_key, values: payload, note: note.trim() || undefined },
      {
        onSuccess: (saved) => {
          setNote("")
          setValues(initial(saved))
          setMaps(initialMaps(saved))
          toast.success(
            saved.current.version_label === policy.current.version_label
              ? "No changes"
              : `Saved as ${saved.current.version_label}`,
            { description: "New analyses use it; earlier runs keep the version they were analyzed with." },
          )
        },
      },
    )
  }

  return (
    <section className="rounded-lg border bg-card p-5 sm:p-6" aria-label={`${policy.agent_name} thresholds`}>
      <div className="flex flex-wrap items-start justify-between gap-3 border-b pb-4">
        <div>
          <h3 className="text-base font-semibold text-brand-navy">{policy.agent_name}</h3>
          <p className="text-xs text-muted-foreground">
            In force: <span className="font-mono">{policy.current.version_label}</span>
            {policy.current.created_by && ` · ${policy.current.created_by}, ${formatDateTime(policy.current.created_at)}`}
          </p>
        </div>
        <Button type="button" size="sm" variant="ghost" onClick={() => setShowHistory((v) => !v)} aria-expanded={showHistory}>
          <History aria-hidden />
          Versions
        </Button>
      </div>

      <form onSubmit={onSubmit} className="space-y-4 pt-4" aria-label={`${policy.agent_name} thresholds`}>
        {save.error && !Object.keys(fieldErrors).length && (
          <Alert>{errorMessage(save.error, "Couldn't save the thresholds.")}</Alert>
        )}
        <div className="grid gap-4 sm:grid-cols-3">
          {policy.fields.filter((f) => !isMap(f)).map((f) => (
            <div key={f.name} className="space-y-1.5">
              <Label htmlFor={`${policy.agent_key}-${f.name}`}>{f.label}</Label>
              <Input
                id={`${policy.agent_key}-${f.name}`}
                inputMode="decimal"
                className="h-10 text-sm"
                value={values[f.name] ?? ""}
                placeholder="Off"
                onChange={(e) => setValues({ ...values, [f.name]: e.target.value })}
                aria-invalid={fieldErrors[f.name] ? true : undefined}
              />
              {fieldErrors[f.name] ? (
                <p className="text-xs text-destructive">{fieldErrors[f.name]}</p>
              ) : (
                f.help && <p className="text-xs text-muted-foreground">{f.help}</p>
              )}
            </div>
          ))}
        </div>
        {policy.fields.filter(isMap).map((f) => (
          <div key={f.name} className="space-y-1.5 sm:max-w-lg">
            <Label htmlFor={`${policy.agent_key}-${f.name}`}>{f.label}</Label>
            <MoneyMapEditor
              id={`${policy.agent_key}-${f.name}`}
              rows={maps[f.name] ?? []}
              onChange={(rows) => setMaps({ ...maps, [f.name]: rows })}
            />
            {mapError ? (
              <p className="text-xs text-destructive">{mapError}</p>
            ) : (
              f.help && <p className="text-xs text-muted-foreground">{f.help}</p>
            )}
          </div>
        ))}
        <div className="flex flex-wrap items-end gap-3">
          <div className="min-w-0 flex-1 space-y-1.5">
            <Label htmlFor={`${policy.agent_key}-note`}>Reason for the change (optional)</Label>
            <Input
              id={`${policy.agent_key}-note`}
              className="h-10 text-sm"
              value={note}
              onChange={(e) => setNote(e.target.value)}
              maxLength={300}
              placeholder="e.g. Q4 tolerance agreed with the Controller"
            />
          </div>
          <Button type="submit" disabled={save.isPending}>
            {save.isPending && <LoaderCircle className="animate-spin" aria-hidden />}
            Save as new version
          </Button>
        </div>
      </form>

      {showHistory && (
        <div className="mt-5 border-t pt-4">
          <VersionList policy={policy} />
        </div>
      )}
    </section>
  )
}
