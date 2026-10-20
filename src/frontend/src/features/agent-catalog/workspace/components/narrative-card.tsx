import { Sparkles, TriangleAlert, LoaderCircle } from "lucide-react"

import type { FormField, Narrative, RunDocument } from "../api"

function List({ title, items }: { title: string; items: string[] }) {
  if (!items.length) return null
  return (
    <div>
      <h4 className="text-xs font-semibold tracking-wide text-muted-foreground uppercase">{title}</h4>
      <ul className="mt-1.5 list-disc space-y-1 pl-5 text-sm">
        {items.map((item) => (
          <li key={item}>{item}</li>
        ))}
      </ul>
    </div>
  )
}

interface NarrativeCardProps {
  pending?: boolean
  narrative: Narrative | null
  fields: FormField[]
  documents: RunDocument[]
}

/** The LLM's explanation, clearly labelled as AI-drafted and with its guard-check results. */
export function NarrativeCard({ narrative, fields, documents, pending }: NarrativeCardProps) {
  return (
    <section aria-labelledby="ai-explanation" className="rounded-lg border border-primary/20 bg-primary/[0.03] p-4 sm:p-5">
      <h3 id="ai-explanation" className="flex items-center gap-2 font-semibold text-primary">
        <Sparkles className="size-4" aria-hidden />
        AI-generated explanation
      </h3>

      {pending ? (
        <p className="mt-2 flex items-center gap-2 text-sm text-muted-foreground" role="status">
          <LoaderCircle className="size-4 animate-spin" aria-hidden />
          Drafting the explanation from the validated results. This page updates by itself.
        </p>
      ) : !narrative || narrative.status === "not_configured" ? (
        <p className="mt-2 text-sm text-muted-foreground">
          AI explanations are turned off (no LLM is configured). The calculations and findings are complete.
        </p>
      ) : narrative.status === "failed" || !narrative.output ? (
        <p className="mt-2 text-sm text-amber-800">
          The AI explanation couldn't be generated{narrative.error ? `: ${narrative.error}` : ""}. The calculations
          and findings are complete and the run can still be submitted.
        </p>
      ) : (
        <NarrativeBody narrative={narrative} fields={fields} documents={documents} />
      )}
    </section>
  )
}

function NarrativeBody({ narrative, fields, documents }: NarrativeCardProps & { narrative: Narrative }) {
  const output = narrative.output!
  const fieldLabel = (key: string) => fields.find((f) => f.name === key)?.label ?? key.replace(/_/g, " ")
  const documentName = (id: string) => {
    const index = Number(id.replace(/^D/, "")) - 1
    return documents[index]?.filename ?? id
  }
  const seconds = narrative.latency_ms !== null ? ` · ${(narrative.latency_ms / 1000).toFixed(1)}s` : ""

  return (
    <div className="mt-3 space-y-4">
      {narrative.guard_warnings.length > 0 && (
        <div className="rounded-md border border-amber-200 bg-amber-50 p-3 text-sm text-amber-900">
          <p className="flex items-center gap-1.5 font-semibold">
            <TriangleAlert className="size-4" aria-hidden />
            Verify before relying on this explanation
          </p>
          <ul className="mt-1 list-disc pl-5">
            {narrative.guard_warnings.map((w) => (
              <li key={w}>{w}</li>
            ))}
          </ul>
        </div>
      )}
      <p className="text-[15px] leading-relaxed">{output.summary}</p>
      <List title="Key points" items={output.key_points} />
      <List title="Missing evidence" items={output.missing_evidence} />
      <List title="Ambiguities" items={output.ambiguities} />
      {(output.cited_fields.length > 0 || output.cited_documents.length > 0) && (
        <div className="flex flex-wrap gap-1.5">
          {output.cited_fields.map((f) => (
            <span key={f} className="rounded bg-secondary px-2 py-0.5 text-xs text-brand-navy">
              {fieldLabel(f)}
            </span>
          ))}
          {output.cited_documents.map((d) => (
            <span key={d} className="rounded bg-blue-50 px-2 py-0.5 text-xs text-blue-800">
              {documentName(d)}
            </span>
          ))}
        </div>
      )}
      <p className="text-xs text-muted-foreground">
        Drafted by {narrative.model} from the validated data above. Verify against the attached source evidence.
        <span className="whitespace-nowrap">
          {" "}
          ({narrative.prompt_version}
          {seconds})
        </span>
      </p>
    </div>
  )
}
