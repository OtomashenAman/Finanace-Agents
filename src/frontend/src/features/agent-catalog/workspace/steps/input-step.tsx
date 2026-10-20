import { useForm } from "react-hook-form"
import { useNavigate } from "react-router"
import { CircleCheck, LoaderCircle } from "lucide-react"
import { toast } from "sonner"

import { Alert } from "@/components/ui/alert"
import { Button } from "@/components/ui/button"
import { SourceRecordPicker } from "@/features/data-sources/components/source-record-picker"
import { ApiError } from "@/lib/api"

import { useAgent } from "../../hooks"
import type { FieldValue, FormField, FormSpec, RunDetail } from "../api"
import { DynamicField, type FormValues } from "../components/dynamic-field"
import { EvidencePanel } from "../components/evidence-panel"
import { Panel } from "../components/panel"
import { SourceSnapshot } from "../components/source-snapshot"
import { parseMoneyInput } from "../format"
import { useAnalyzeRun, useDeleteRun, useSaveInput } from "../hooks"

function toFormValues(fields: FormField[], input: Record<string, FieldValue>): FormValues {
  return Object.fromEntries(
    fields.map((f) => {
      const value = input[f.name]
      return [f.name, f.kind === "boolean" ? value === true : value === null || value === undefined ? "" : String(value)]
    }),
  )
}

function toPayload(fields: FormField[], values: FormValues): Record<string, FieldValue> {
  return Object.fromEntries(
    fields.map((f) => {
      const raw = values[f.name]
      if (f.kind === "boolean") return [f.name, raw === true]
      const text = typeof raw === "string" ? raw.trim() : ""
      if (!text) return [f.name, null]
      return [f.name, f.kind === "text" || f.kind === "textarea" ? text : parseMoneyInput(text)]
    }),
  )
}

interface InputStepProps {
  agentKey: string
  run: RunDetail
  form: FormSpec
}

export function InputStep({ agentKey, run, form }: InputStepProps) {
  const navigate = useNavigate()
  const save = useSaveInput(agentKey, run.id)
  const analyze = useAnalyzeRun(agentKey, run.id)
  const deleteRun = useDeleteRun(agentKey, run.id)
  const { data: agent } = useAgent(agentKey)
  const recordType = agent?.source_record_type ?? null
  const canEdit = run.permissions.can_edit
  const busy = save.isPending || analyze.isPending

  const {
    register,
    handleSubmit,
    setError,
    reset,
    formState: { errors },
  } = useForm<FormValues>({ defaultValues: toFormValues(form.fields, run.input) })

  const serverErrors = Object.fromEntries(
    (run.validation_errors ?? []).filter((e) => e.field).map((e) => [e.field as string, e.message]),
  )

  const persist = async (values: FormValues) => {
    try {
      return await save.mutateAsync(toPayload(form.fields, values))
    } catch (error) {
      if (error instanceof ApiError) {
        for (const [field, message] of Object.entries(error.fieldErrors)) setError(field, { message })
        toast.error(error.message)
      } else {
        toast.error("Couldn't save the form")
      }
      return null
    }
  }

  const onSave = handleSubmit(async (values) => {
    if (await persist(values)) toast.success("Draft saved")
  })

  const onAnalyze = handleSubmit(async (values) => {
    if (!(await persist(values))) return
    try {
      const result = await analyze.mutateAsync()
      if (result.status === "validation_failed") toast.error("Some required fields are missing or invalid")
    } catch (error) {
      toast.error(error instanceof ApiError ? error.message : "Analysis failed")
    }
  })

  const onDelete = () =>
    deleteRun.mutate(undefined, {
      onSuccess: () => {
        toast.success(`${run.reference} deleted`)
        void navigate(`/catalog/${agentKey}`)
      },
      onError: (error) => toast.error(error instanceof ApiError ? error.message : "Couldn't delete the draft"),
    })

  return (
    <div className="grid gap-6 lg:grid-cols-[minmax(0,1.55fr)_minmax(0,1fr)]">
      <Panel title="Input data">
        <form onSubmit={onSave} noValidate aria-label="Input data">
          {run.validation_errors && (
            <Alert className="mb-5">Some required fields are missing or invalid. Correct them and analyze again.</Alert>
          )}
          {canEdit && recordType && (
            <div className="mb-5">
              <SourceRecordPicker
                agentKey={agentKey}
                run={run}
                recordType={recordType}
                onLinked={(updated) => reset(toFormValues(form.fields, updated.input))}
              />
            </div>
          )}
          {!canEdit && run.source && (
            <div className="mb-5">
              <SourceSnapshot source={run.source} />
            </div>
          )}
          <fieldset disabled={!canEdit || busy} className="grid gap-x-6 gap-y-5 sm:grid-cols-2">
            {form.fields.map((field) => (
              <DynamicField
                key={field.name}
                field={field}
                register={register}
                error={errors[field.name]?.message ?? serverErrors[field.name]}
                disabled={!canEdit || busy}
              />
            ))}
          </fieldset>
          <div className="mt-6 flex flex-wrap items-center justify-between gap-3 border-t pt-5">
            <p className="text-xs text-muted-foreground">
              {run.source
                ? `Prefilled from ${run.source.source_name}; edit anything the source doesn't know.`
                : "Enter the values, or prefill them from your QuickBooks or uploaded data."}
            </p>
            {canEdit && (
              <div className="flex gap-2">
                {run.permissions.can_delete && (
                  <Button type="button" variant="ghost" size="sm" onClick={onDelete} disabled={busy || deleteRun.isPending}>
                    Delete draft
                  </Button>
                )}
                <Button type="submit" variant="outline" size="sm" disabled={busy}>
                  {save.isPending && !analyze.isPending ? "Saving…" : "Save draft"}
                </Button>
              </div>
            )}
          </div>
        </form>
      </Panel>

      <Panel title="Source evidence">
        <div className="space-y-6">
          <EvidencePanel agentKey={agentKey} run={run} canEdit={canEdit && !busy} />

          <div>
            <h3 className="text-sm font-semibold text-brand-navy">Validation</h3>
            <ul className="mt-2 space-y-1.5 text-sm">
              {form.controls.map((control) => (
                <li key={control} className="flex items-center gap-2">
                  <CircleCheck className="size-4 text-emerald-600" aria-hidden />
                  {control}
                </li>
              ))}
            </ul>
          </div>

          {canEdit && (
            <div aria-live="polite">
              <Button type="button" size="lg" className="w-full font-semibold" onClick={() => void onAnalyze()} disabled={busy}>
                {analyze.isPending ? (
                  <>
                    <LoaderCircle className="animate-spin" aria-hidden />
                    Analyzing…
                  </>
                ) : (
                  "Validate & Analyze"
                )}
              </Button>
              {analyze.isPending && (
                <p className="mt-2 text-center text-xs text-muted-foreground">
                  Running checks and drafting the AI explanation. This can take a few seconds.
                </p>
              )}
            </div>
          )}
        </div>
      </Panel>
    </div>
  )
}
