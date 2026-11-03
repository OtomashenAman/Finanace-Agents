import { useState, type FormEvent } from "react"
import { Plus, Trash2 } from "lucide-react"

import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Textarea } from "@/components/ui/textarea"
import type { Artifact } from "@/features/service-pod/api"
import { ARTIFACT_KIND } from "@/features/service-pod/labels"

import type { JsonSchema, L5 } from "../api"

/** A field's value while it's being filled in: text, a tick, a list of document ids, or the
 *  rows of a list of objects (each field as text). */
type Value = string | boolean | string[] | Record<string, string>[]
type Values = Record<string, Record<string, Value>>

const selectClass = "flex h-9 w-full rounded-md border border-input bg-background px-2 text-sm"

/** The field's own schema, with `X | None` (anyOf with null) and $ref resolved; the outer
 *  title, description, examples and x- hints are kept. */
function resolve(schema: JsonSchema, root: JsonSchema): { schema: JsonSchema; optional: boolean } {
  const keep = {
    title: schema.title, description: schema.description, examples: schema.examples,
    "x-labels": schema["x-labels"], "x-document": schema["x-document"],
  }
  let s = schema
  let optional = false
  if (s.anyOf) {
    const real = s.anyOf.filter((a) => a.type !== "null")
    optional = real.length < s.anyOf.length
    s = { ...real[0] }
  }
  if (s.$ref) {
    const name = s.$ref.split("/").at(-1) ?? ""
    s = { ...(root.$defs?.[name] ?? {}) }
  }
  const merged = { ...s }
  for (const [k, v] of Object.entries(keep)) if (v !== undefined) (merged as Record<string, unknown>)[k] = v
  return { schema: merged, optional }
}

const isNumber = (s: JsonSchema) => s.type === "integer" || s.type === "number"
const isDocument = (s: JsonSchema) => Boolean(s["x-document"])
const human = (option: string, s: JsonSchema) =>
  s["x-labels"]?.[option] ?? option.replace(/_/g, " ").replace(/^\w/, (c) => c.toUpperCase())
const example = (s: JsonSchema) => (s.examples?.length ? `e.g. ${String(s.examples[0])}` : undefined)

function scalar(raw: string, s: JsonSchema): unknown {
  if (s.format === "date-time") return new Date(raw).toISOString()
  if (s.type === "integer") return Number.parseInt(raw, 10)
  if (s.type === "number") return Number(raw)
  return raw
}

function convert(raw: Value, schema: JsonSchema, root: JsonSchema): unknown {
  if (typeof raw === "boolean") return raw
  if (typeof raw === "string") return scalar(raw, schema)
  if (raw.length === 0) return []
  if (typeof raw[0] === "string") return raw
  // rows of a list of objects: each field converted; rows left empty are dropped
  const item = schema.items ? resolve(schema.items, root).schema : {}
  return (raw as Record<string, string>[])
    .filter((row) => Object.values(row).some((v) => v.trim() !== ""))
    .map((row) =>
      Object.fromEntries(
        Object.entries(row)
          .filter(([, v]) => v.trim() !== "")
          .map(([k, v]) => [k, scalar(v, resolve(item.properties?.[k] ?? {}, root).schema)]),
      ),
    )
}

/** What was filled in before (a step sent back), as form values. */
function startFrom(previous: Record<string, unknown> | null | undefined): Record<string, Value> {
  const out: Record<string, Value> = {}
  for (const [k, v] of Object.entries(previous ?? {})) {
    if (v === null || v === undefined) continue
    if (typeof v === "boolean" || typeof v === "string") out[k] = v
    else if (typeof v === "number") out[k] = String(v)
    else if (Array.isArray(v)) {
      out[k] = v.every((x) => typeof x === "string")
        ? (v as string[])
        : (v as Record<string, unknown>[]).map((row) => Object.fromEntries(Object.entries(row).map(([a, b]) => [a, b == null ? "" : String(b)])))
    }
  }
  return out
}

function Help({ schema }: { schema: JsonSchema }) {
  return schema.description ? <span className="block text-xs text-muted-foreground">{schema.description}</span> : null
}

/** One field, by what it holds: a tick, a choice, a document of the case, a list, or text. */
function Field({ id, field, schema, required, value, set, root, documents }: {
  id: string
  field: string
  schema: JsonSchema
  required: boolean
  value: Value | undefined
  set: (value: Value) => void
  root: JsonSchema
  documents: Artifact[]
}) {
  const label = `${schema.title ?? field}${required ? " *" : ""}`
  if (schema.type === "boolean" || schema.const === true) {
    return (
      <label htmlFor={id} className="flex items-start gap-2 text-sm">
        <input id={id} type="checkbox" className="mt-1" checked={value === true} onChange={(e) => set(e.target.checked)} />
        <span>{label}<Help schema={schema} /></span>
      </label>
    )
  }
  const kinds = schema["x-document"] ?? schema.items?.["x-document"]
  const docs = kinds ? documents.filter((d) => kinds.includes(d.kind)) : documents
  const noDocs = (
    <span className="block rounded-md border border-dashed border-border px-3 py-2 text-xs text-muted-foreground">
      No {kinds?.map((k) => ARTIFACT_KIND[k as keyof typeof ARTIFACT_KIND] ?? k).join(" or ")} document in this case yet: add it under Documents, then choose it here.
    </span>
  )
  if (schema.type === "array" && schema.items && (isDocument(schema) || isDocument(schema.items))) {
    const chosen = Array.isArray(value) ? (value as string[]) : []
    return (
      <fieldset className="space-y-1 text-sm">
        <legend className="font-medium">{label}</legend>
        <Help schema={schema} />
        {docs.length === 0 ? noDocs : docs.map((d) => (
          <label key={d.id} className="flex items-center gap-2">
            <input type="checkbox" checked={chosen.includes(d.id)}
              onChange={(e) => set(e.target.checked ? [...chosen, d.id] : chosen.filter((x) => x !== d.id))} />
            {d.filename}
          </label>
        ))}
      </fieldset>
    )
  }
  if (schema.type === "array" && schema.items) {
    const item = resolve(schema.items, root).schema
    if (item.type === "object" && item.properties) {
      const rows = Array.isArray(value) ? (value as Record<string, string>[]) : []
      const sub = Object.entries(item.properties)
      const subRequired = new Set(item.required ?? [])
      const setRow = (i: number, k: string, v: string) => set(rows.map((r, j) => (j === i ? { ...r, [k]: v } : r)))
      return (
        <fieldset className="space-y-2 text-sm">
          <legend className="font-medium">{label}</legend>
          <Help schema={schema} />
          {rows.map((row, i) => (
            <div key={i} className="grid gap-2 rounded-md border border-border/70 p-2 sm:grid-cols-[repeat(auto-fit,minmax(10rem,1fr))_auto]">
              {sub.map(([k, prop]) => {
                const s = resolve(prop, root).schema
                return (
                  <Input key={k} aria-label={`${s.title ?? k}, row ${i + 1}`} placeholder={`${s.title ?? k}${subRequired.has(k) ? " *" : ""}${example(s) ? ` (${example(s)})` : ""}`}
                    type={isNumber(s) ? "number" : s.format === "email" ? "email" : "text"} step="any"
                    value={row[k] ?? ""} onChange={(e) => setRow(i, k, e.target.value)} />
                )
              })}
              <Button type="button" variant="ghost" size="icon" aria-label={`Remove row ${i + 1}`} onClick={() => set(rows.filter((_, j) => j !== i))}>
                <Trash2 className="size-4" aria-hidden />
              </Button>
            </div>
          ))}
          {rows.length < (schema.maxItems ?? 50) && (
            <Button type="button" variant="outline" size="sm" onClick={() => set([...rows, {}])}>
              <Plus className="size-4" aria-hidden /> Add {rows.length ? "another" : "one"}
            </Button>
          )}
        </fieldset>
      )
    }
    const lines = Array.isArray(value) ? (value as string[]).join("\n") : ""
    return (
      <label htmlFor={id} className="block space-y-1 text-sm">
        <span className="font-medium">{label}</span>
        <Textarea id={id} rows={3} placeholder="One per line" value={lines}
          onChange={(e) => set(e.target.value.split("\n").map((l) => l.trim()).filter(Boolean))} />
        <Help schema={schema} />
      </label>
    )
  }
  const text = typeof value === "string" ? value : ""
  return (
    <label htmlFor={id} className="block space-y-1 text-sm">
      <span className="font-medium">{label}</span>
      {isDocument(schema) ? (
        docs.length === 0 ? noDocs : (
          <select id={id} className={selectClass} value={text} onChange={(e) => set(e.target.value)}>
            <option value="">Choose a document…</option>
            {docs.map((d) => <option key={d.id} value={d.id}>{d.filename}</option>)}
          </select>
        )
      ) : schema.enum ? (
        <select id={id} className={selectClass} value={text} onChange={(e) => set(e.target.value)}>
          <option value="">Choose…</option>
          {schema.enum.map((option) => (
            <option key={String(option)} value={String(option)}>{human(String(option), schema)}</option>
          ))}
        </select>
      ) : schema.type === "string" && (schema.maxLength ?? 0) > 300 ? (
        <Textarea id={id} rows={2} placeholder={example(schema)} value={text} onChange={(e) => set(e.target.value)} />
      ) : (
        <Input
          id={id}
          type={schema.format === "date-time" ? "datetime-local" : schema.format === "date" ? "date" : isNumber(schema) ? "number" : schema.format === "email" ? "email" : "text"}
          step={isNumber(schema) ? "any" : undefined}
          placeholder={example(schema)}
          value={text}
          onChange={(e) => set(e.target.value)}
        />
      )}
      <Help schema={schema} />
    </label>
  )
}

/** Fill in a person's L5 results from the schema the backend declares for each step: each
 *  field says what goes in it, lists get rows, documents are chosen from the case's own. */
export function ResultForm({
  l5,
  busy,
  submitLabel,
  onSubmit,
  documents = [],
}: {
  l5: L5[]
  busy: boolean
  submitLabel: string
  onSubmit: (results: Record<string, Record<string, unknown>>) => void
  documents?: Artifact[]
}) {
  const [values, setValues] = useState<Values>(() => Object.fromEntries(l5.map((s) => [s.code, startFrom(s.previous)])))
  const set = (code: string, field: string, value: Value) => setValues((v) => ({ ...v, [code]: { ...v[code], [field]: value } }))

  const submit = (e: FormEvent) => {
    e.preventDefault()
    const results: Record<string, Record<string, unknown>> = {}
    for (const step of l5) {
      const out: Record<string, unknown> = {}
      for (const [field, prop] of Object.entries(step.result_schema.properties ?? {})) {
        const raw = values[step.code]?.[field]
        if (raw === undefined || raw === "") continue
        out[field] = convert(raw, resolve(prop, step.result_schema).schema, step.result_schema)
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
          <fieldset key={step.code} className="space-y-3 rounded-md border border-border/70 bg-background/70 p-3">
            <legend className="px-1 text-xs font-semibold text-muted-foreground">
              {step.code} · {step.text}
            </legend>
            {props.map(([field, prop]) => {
              const { schema, optional } = resolve(prop, step.result_schema)
              return (
                <Field key={field} id={`${step.code}-${field}`} field={field} schema={schema}
                  required={required.has(field) && !optional} value={values[step.code]?.[field]}
                  set={(v) => set(step.code, field, v)} root={step.result_schema} documents={documents} />
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
