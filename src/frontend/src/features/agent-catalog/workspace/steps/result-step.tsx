import { LoaderCircle } from "lucide-react"
import { toast } from "sonner"

import { Button } from "@/components/ui/button"
import { ApiError } from "@/lib/api"

import type { FormSpec, RunDetail } from "../api"
import { CalculationsTable, FindingsList } from "../components/findings-list"
import { NarrativeCard } from "../components/narrative-card"
import { Panel } from "../components/panel"
import { StatusBadge } from "../components/status-badge"
import type { Step } from "../components/stepper"
import { useAnalyzeRun, useSubmitRun } from "../hooks"

interface ResultStepProps {
  agentKey: string
  run: RunDetail
  form: FormSpec
  onGoTo: (step: Step) => void
}

export function ResultStep({ agentKey, run, form, onGoTo }: ResultStepProps) {
  const submit = useSubmitRun(agentKey, run.id)
  const analyze = useAnalyzeRun(agentKey, run.id)
  const busy = submit.isPending || analyze.isPending

  const onSubmit = () =>
    submit.mutate(undefined, {
      onSuccess: () => toast.success(`${run.reference} sent to ${run.reviewer_label} for approval`),
      onError: (error) => toast.error(error instanceof ApiError ? error.message : "Couldn't submit the run"),
    })

  const onReanalyze = () =>
    analyze.mutate(undefined, {
      onError: (error) => toast.error(error instanceof ApiError ? error.message : "Analysis failed"),
    })

  return (
    <div className="grid gap-6 lg:grid-cols-[minmax(0,1.55fr)_minmax(0,1fr)]">
      <Panel
        title={`Analysis result · ${run.reference}`}
        action={<StatusBadge status={run.status} label={run.status_label} />}
      >
        <div className="space-y-6">
          <p className="text-2xl font-bold text-brand-navy">{run.headline}</p>
          <FindingsList flags={run.flags} />
          <div>
            <h3 className="mb-1 text-sm font-semibold text-brand-navy">Calculations</h3>
            <CalculationsTable calculations={run.calculations} />
          </div>
          <NarrativeCard narrative={run.narrative} fields={form.fields} documents={run.documents} />
        </div>
      </Panel>

      <Panel title="Validation & evidence">
        <div className="space-y-6">
          <span className="inline-flex rounded bg-emerald-50 px-3 py-1.5 text-xs font-semibold text-emerald-800">
            Calculations complete
          </span>

          <div>
            <h3 className="text-sm font-semibold text-brand-navy">Review these controls:</h3>
            <ul className="mt-2 list-disc space-y-1.5 pl-5 text-sm">
              {run.controls.map((control) => (
                <li key={control}>{control}</li>
              ))}
            </ul>
          </div>

          <div>
            <h3 className="text-sm font-semibold text-brand-navy">Proposed decision</h3>
            <p className="mt-1 text-sm">{run.proposed_decision}</p>
          </div>

          <div>
            <h3 className="text-sm font-semibold text-brand-navy">Evidence</h3>
            <p className="mt-1 text-sm text-muted-foreground">
              {run.documents.length
                ? run.documents.map((d) => d.filename).join(", ")
                : "No supporting documents attached."}
            </p>
          </div>

          <div className="space-y-2">
            {run.permissions.can_submit && (
              <Button size="lg" className="w-full font-semibold" onClick={onSubmit} disabled={busy}>
                {submit.isPending ? "Submitting…" : "Submit for approval"}
              </Button>
            )}
            {run.permissions.can_edit && (
              <div className="flex gap-2">
                <Button variant="outline" className="flex-1" onClick={() => onGoTo("input")} disabled={busy}>
                  Edit input
                </Button>
                <Button variant="outline" className="flex-1" onClick={onReanalyze} disabled={busy}>
                  {analyze.isPending && <LoaderCircle className="animate-spin" aria-hidden />}
                  Analyze again
                </Button>
              </div>
            )}
            {!run.permissions.can_submit && run.status === "analyzed" && (
              <p className="text-sm text-muted-foreground">Waiting for the preparer to submit this run.</p>
            )}
          </div>
        </div>
      </Panel>
    </div>
  )
}
