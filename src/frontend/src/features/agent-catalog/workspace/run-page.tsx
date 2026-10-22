import { useState } from "react"
import { Link, useParams } from "react-router"
import { ArrowLeft, LoaderCircle } from "lucide-react"

import { AppPage } from "@/components/layout/app-page"
import { Alert } from "@/components/ui/alert"
import { ApiError } from "@/lib/api"

import { useAgent } from "../hooks"
import type { RunStatus } from "./api"
import { StatusBadge } from "./components/status-badge"
import { Stepper, type Step } from "./components/stepper"
import { useFormSpec, useRun } from "./hooks"
import { InputStep } from "./steps/input-step"
import { ResultStep } from "./steps/result-step"
import { ReviewStep } from "./steps/review-step"

/** Furthest step a run has reached, and the step to open by default. */
function stepsFor(status: RunStatus): { reached: Step; initial: Step } {
  switch (status) {
    case "draft":
    case "validation_failed":
      return { reached: "input", initial: "input" }
    case "analyzed":
      return { reached: "result", initial: "result" }
    case "changes_requested":
      return { reached: "review", initial: "input" }
    default:
      return { reached: "review", initial: "review" }
  }
}

const SUBTITLES: Record<Step, string> = {
  input: "Complete the input form and attach supporting documents, then validate and analyze.",
  result: "Check the calculations, findings and AI explanation before sending to the reviewer.",
  review: "The reviewer inspects the evidence and records a decision. Every decision is audited.",
}

export function RunPage() {
  const { agentKey = "", runId = "" } = useParams()
  const agent = useAgent(agentKey)
  const run = useRun(agentKey, runId)
  const form = useFormSpec(agentKey)
  // A step picked by the user, valid only while the run stays in the status it was picked in
  const [picked, setPicked] = useState<{ step: Step; status: RunStatus } | null>(null)

  if (agent.isPending || run.isPending || form.isPending) {
    return (
      <AppPage title="Agent workspace">
        <div className="flex justify-center py-16" role="status">
          <LoaderCircle className="size-6 animate-spin text-primary" aria-hidden />
          <span className="sr-only">Loading run…</span>
        </div>
      </AppPage>
    )
  }

  if (agent.error || run.error || form.error || !agent.data || !run.data || !form.data) {
    const error = run.error ?? agent.error ?? form.error
    const notFound = error instanceof ApiError && error.status === 404
    return (
      <AppPage title="Agent workspace">
        <div className="space-y-4">
          <Alert>{notFound ? "This run doesn't exist or you don't have access to it." : "Couldn't load this run."}</Alert>
          <Link to={`/catalog/${agentKey}`} className="text-sm font-medium text-primary hover:underline">
            Back to the agent
          </Link>
        </div>
      </AppPage>
    )
  }

  const data = run.data
  const { reached, initial } = stepsFor(data.status)
  const current = picked && picked.status === data.status ? picked.step : initial
  const goTo = (step: Step) => setPicked({ step, status: data.status })

  return (
    <AppPage title={agent.data.name} subtitle={SUBTITLES[current]}>
      <div className="mb-5 flex flex-wrap items-center justify-between gap-3">
        <Link
          to={`/catalog/${agentKey}`}
          className="inline-flex items-center gap-1.5 text-sm font-medium text-primary hover:underline"
        >
          <ArrowLeft className="size-4" aria-hidden />
          All {agent.data.short_name} runs
        </Link>
        <div className="flex items-center gap-3 text-sm">
          <span className="font-semibold text-brand-navy">{data.reference}</span>
          {data.business_reference && <span className="text-muted-foreground">{data.business_reference}</span>}
          <StatusBadge status={data.status} label={data.status_label} />
        </div>
      </div>

      <Stepper current={current} reached={reached} onSelect={goTo} />

      <div className="mt-5">
        {current === "input" && <InputStep key={data.id} agentKey={agentKey} run={data} form={form.data} />}
        {current === "result" && <ResultStep agentKey={agentKey} run={data} form={form.data} onGoTo={goTo} />}
        {current === "review" && <ReviewStep agentKey={agentKey} run={data} />}
      </div>
    </AppPage>
  )
}
