import { useState } from "react"
import { Link } from "react-router"
import { Database, LoaderCircle, Unlink } from "lucide-react"
import { toast } from "sonner"

import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import type { FieldValue, FormField, RunDetail } from "@/features/agent-catalog/workspace/api"
import { formatDateTime } from "@/features/agent-catalog/workspace/format"
import { usePrefillFromData, usePrefillOptions, useUnlinkSource } from "@/features/agent-catalog/workspace/hooks"
import { ApiError, errorMessage } from "@/lib/api"

import { useDataSources } from "../hooks"

const SELECT =
  "flex h-10 w-full rounded-md border border-input bg-background px-3 text-sm focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/20 focus-visible:outline-none"

interface Props {
  agentKey: string
  run: RunDetail
  /** The agent's prefill parameters (form spec prefill_fields) */
  fields: FormField[]
  /** Called with the prefilled run so the form can show the new values */
  onPrefilled: (run: RunDetail) => void
}

function initial(fields: FormField[], run: RunDetail): Record<string, string> {
  const used = (run.source?.records.parameters ?? {}) as Record<string, unknown>
  return Object.fromEntries(fields.map((f) => [f.name, String(used[f.name] ?? f.default ?? "")]))
}

/** Prefill a run from figures computed over the user's data source (e.g. cash over a horizon). */
export function SourceParamsPrefill({ agentKey, run, fields, onPrefilled }: Props) {
  const sources = useDataSources()
  const prefill = usePrefillFromData(agentKey, run.id)
  const unlink = useUnlinkSource(agentKey, run.id)
  const [editing, setEditing] = useState(run.source === null)
  const [sourceId, setSourceId] = useState<string | null>(null)
  const [values, setValues] = useState(() => initial(fields, run))

  const usable = (sources.data ?? []).filter((s) => Object.values(s.record_counts).some((n) => (n ?? 0) > 0))
  const selected = sourceId ?? run.source?.source_id ?? usable[0]?.id ?? null
  const busy = prefill.isPending || unlink.isPending
  const fieldErrors = prefill.error instanceof ApiError ? prefill.error.fieldErrors : {}
  // Choices without fixed options come from the selected source (e.g. its accounts)
  const needsOptions = fields.some((f) => f.kind === "choice" && !f.options)
  const options = usePrefillOptions(agentKey, editing && needsOptions ? selected : null)
  const choicesOf = (f: FormField): string[] => f.options ?? options.data?.[f.name] ?? []
  /** What the field submits: a choice defaults to its first option */
  const valueOf = (f: FormField): string => {
    const value = values[f.name] ?? ""
    if (f.kind !== "choice") return value
    const choices = choicesOf(f)
    return choices.includes(value) ? value : (choices[0] ?? "")
  }
  const missingChoices = fields.some((f) => f.kind === "choice" && options.data && choicesOf(f).length === 0)

  const onPrefill = () => {
    if (!selected) return
    const params: Record<string, FieldValue> = Object.fromEntries(
      fields.map((f) => [f.name, valueOf(f).trim() || null]),
    )
    prefill.mutate(
      { sourceId: selected, params },
      {
        onSuccess: (updated) => {
          setEditing(false)
          onPrefilled(updated)
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
        setEditing(true)
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
        {run.source && !editing && (
          <div className="flex gap-1">
            <Button type="button" size="sm" variant="ghost" onClick={() => setEditing(true)} disabled={busy}>
              Prefill again
            </Button>
            <Button type="button" size="sm" variant="ghost" onClick={onUnlink} disabled={busy}>
              <Unlink aria-hidden />
              Unlink
            </Button>
          </div>
        )}
      </div>

      {run.source && !editing && (
        <p className="mt-2 text-sm">
          From <span className="font-semibold">{run.source.source_name}</span>:{" "}
          <span className="font-semibold">{run.source.record_reference}</span>
          <span className="block text-xs text-muted-foreground">
            Captured {formatDateTime(run.source.captured_at)}; the reviewer sees this snapshot.
          </span>
        </p>
      )}

      {editing && (
        <div className="mt-3 space-y-3">
          {sources.isPending && <LoaderCircle className="size-4 animate-spin text-primary" aria-label="Loading" />}
          {sources.data && usable.length === 0 && (
            <p className="text-sm text-muted-foreground">
              You have no data yet.{" "}
              <Link to="/data-sources" className="font-medium text-primary hover:underline">
                Connect QuickBooks or upload a file
              </Link>
              , or enter the values manually.
            </p>
          )}
          {usable.length > 0 && (
            // A div, not a form: this panel sits inside the run's input form
            <div className="space-y-3" role="group" aria-label="Prefill parameters">
              <div className="grid gap-3 sm:grid-cols-2">
                <div className="space-y-1.5">
                  <Label htmlFor="prefill-source" className="text-xs">
                    Data source
                  </Label>
                  <select
                    id="prefill-source"
                    className={SELECT}
                    value={selected ?? ""}
                    onChange={(e) => setSourceId(e.target.value)}
                  >
                    {usable.map((s) => (
                      <option key={s.id} value={s.id}>
                        {s.name}
                      </option>
                    ))}
                  </select>
                </div>
                {fields.map((f) => (
                  <div key={f.name} className="space-y-1.5">
                    <Label htmlFor={`prefill-${f.name}`} className="text-xs">
                      {f.label}
                    </Label>
                    {f.kind === "choice" ? (
                      <select
                        id={`prefill-${f.name}`}
                        className={SELECT}
                        value={valueOf(f)}
                        onChange={(e) => setValues({ ...values, [f.name]: e.target.value })}
                        disabled={choicesOf(f).length === 0}
                        aria-invalid={fieldErrors[f.name] ? true : undefined}
                      >
                        {choicesOf(f).map((choice) => (
                          <option key={choice} value={choice}>
                            {choice}
                          </option>
                        ))}
                      </select>
                    ) : (
                      <Input
                        id={`prefill-${f.name}`}
                        inputMode={f.kind === "number" || f.kind === "money" ? "decimal" : undefined}
                        className="h-10 text-sm"
                        value={values[f.name] ?? ""}
                        onChange={(e) => setValues({ ...values, [f.name]: e.target.value })}
                        aria-invalid={fieldErrors[f.name] ? true : undefined}
                      />
                    )}
                    {fieldErrors[f.name] ? (
                      <p className="text-xs text-destructive">{fieldErrors[f.name]}</p>
                    ) : (
                      f.help && <p className="text-xs text-muted-foreground">{f.help}</p>
                    )}
                  </div>
                ))}
              </div>
              {options.isPending && needsOptions && (
                <LoaderCircle className="size-4 animate-spin text-primary" aria-label="Loading choices" />
              )}
              {missingChoices && (
                <p className="text-sm text-muted-foreground">
                  This source has nothing to choose from yet (QuickBooks month-end balances arrive in the
                  background after a sync), or enter the values manually.
                </p>
              )}
              <div className="flex gap-2">
                <Button type="button" size="sm" onClick={onPrefill} disabled={busy || !selected || missingChoices}>
                  {prefill.isPending && <LoaderCircle className="animate-spin" aria-hidden />}
                  Prefill
                </Button>
                {run.source && (
                  <Button type="button" size="sm" variant="ghost" onClick={() => setEditing(false)}>
                    Keep the current values
                  </Button>
                )}
              </div>
            </div>
          )}
        </div>
      )}
    </section>
  )
}
