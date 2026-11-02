import { useState, type FormEvent } from "react"

import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Textarea } from "@/components/ui/textarea"

import type { JsonSchema, L5 } from "../api"

type Values = Record<string, Record<string, string | boolean>>

/** The field's own schema, with `X | None` (anyOf with null) and $ref resolved. */
function resolve(schema: JsonSchema, root: JsonSchema): { schema: JsonSchema; optional: boolean } {
  let s = schema
  let optional = false
  if (s.anyOf) {
    const real = s.anyOf.filter((a) => a.type !== "null")
    optional = real.length < s.anyOf.length
    s = { ...real[0], title: s.title, description: s.description }
  }
  if (s.$ref) {
    const name = s.$ref.split("/").at(-1) ?? ""
    s = { ...(root.$defs?.[name] ?? {}), title: s.title ?? root.$defs?.[name]?.title }
  }
  return { schema: s, optional }
}

function convert(raw: string | boolean, schema: JsonSchema): unknown {
  if (typeof raw === "boolean") return raw
  if (schema.format === "date-time") return new Date(raw).toISOString()
  if (schema.type === "integer") return Number.parseInt(raw, 10)
  if (schema.type === "number") return Number(raw)
  return raw
}

/** Fill in a person's L5 results from the schema the backend declares for each step. */
export function ResultForm({
  l5,
  busy,
  submitLabel,
  onSubmit,
}: {
  l5: L5[]
  busy: boolean
  submitLabel: string
  onSubmit: (results: Record<string, Record<string, unknown>>) => void
}) {
  const [values, setValues] = useState<Values>({})
  const set = (code: string, field: string, value: string | boolean) =>
    setValues((v) => ({ ...v, [code]: { ...v[code], [field]: value } }))

  const submit = (e: FormEvent) => {
    e.preventDefault()
    const results: Record<string, Record<string, unknown>> = {}
    for (const step of l5) {
      const out: Record<string, unknown> = {}
      for (const [field, prop] of Object.entries(step.result_schema.properties ?? {})) {
        const raw = values[step.code]?.[field]
        if (raw === undefined || raw === "") continue
        out[field] = convert(raw, resolve(prop, step.result_schema).schema)
      }
      results[step.code] = out
    }
    onSubmit(results)
  }

  return (
    <form onSubmit={submit} className="space-y-3">
      {l5.map((step) => {
        const props = Object.entries(step.result_schema.properties ?? {})
        const required = new Set(step.result_schema.required ?? [])
        return (
          <fieldset key={step.code} className="space-y-2 rounded-md border border-border/70 bg-background/70 p-3">
            <legend className="px-1 text-xs font-semibold text-muted-foreground">
              {step.code} · {step.text}
            </legend>
            {props.map(([field, prop]) => {
              const { schema, optional } = resolve(prop, step.result_schema)
              const label = `${schema.title ?? field}${required.has(field) && !optional ? " *" : ""}`
              const value = values[step.code]?.[field]
              const id = `${step.code}-${field}`
              if (schema.type === "boolean" || schema.const === true) {
                return (
                  <label key={field} htmlFor={id} className="flex items-center gap-2 text-sm">
                    <input
                      id={id}
                      type="checkbox"
                      checked={value === true}
                      onChange={(e) => set(step.code, field, e.target.checked)}
                    />
                    {label}
                  </label>
                )
              }
              return (
                <label key={field} htmlFor={id} className="block space-y-1 text-sm">
                  <span className="font-medium">{label}</span>
                  {schema.enum ? (
                    <select
                      id={id}
                      className="flex h-9 w-full rounded-md border border-input bg-background px-2 text-sm"
                      value={typeof value === "string" ? value : ""}
                      onChange={(e) => set(step.code, field, e.target.value)}
                    >
                      <option value="">Choose…</option>
                      {schema.enum.map((option) => (
                        <option key={String(option)} value={String(option)}>
                          {String(option).replace(/_/g, " ")}
                        </option>
                      ))}
                    </select>
                  ) : schema.type === "string" && (schema.maxLength ?? 0) > 300 ? (
                    <Textarea
                      id={id}
                      rows={2}
                      value={typeof value === "string" ? value : ""}
                      onChange={(e) => set(step.code, field, e.target.value)}
                    />
                  ) : (
                    <Input
                      id={id}
                      type={
                        schema.format === "date-time"
                          ? "datetime-local"
                          : schema.format === "date"
                            ? "date"
                            : schema.type === "integer" || schema.type === "number"
                              ? "number"
                              : "text"
                      }
                      value={typeof value === "string" ? value : ""}
                      onChange={(e) => set(step.code, field, e.target.value)}
                    />
                  )}
                  {schema.description && <span className="block text-xs text-muted-foreground">{schema.description}</span>}
                </label>
              )
            })}
          </fieldset>
        )
      })}
      <Button type="submit" size="sm" disabled={busy}>
        {submitLabel}
      </Button>
    </form>
  )
}
