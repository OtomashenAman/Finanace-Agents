import { ArrowLeft, LoaderCircle } from "lucide-react"
import { Link, useParams } from "react-router"

import { AppPage } from "@/components/layout/app-page"
import { Alert } from "@/components/ui/alert"
import { ApiError } from "@/lib/api"

import type { AgentCapacity } from "./api"
import { useAgent } from "./hooks"

const CAPACITY_LABELS: Record<AgentCapacity, string> = { preparer: "Preparer", reviewer: "Reviewer" }

function BackLink() {
  return (
    <Link to="/catalog" className="inline-flex items-center gap-1.5 text-sm font-medium text-primary hover:underline">
      <ArrowLeft className="size-4" aria-hidden />
      Back to catalog
    </Link>
  )
}

/** Placeholder until each agent's input / result / review workspace is built. */
export function WorkspacePage() {
  const { agentKey = "" } = useParams()
  const { data: agent, isPending, error } = useAgent(agentKey)

  if (isPending) {
    return (
      <AppPage title="Agent workspace">
        <div className="flex justify-center py-16" role="status">
          <LoaderCircle className="size-6 animate-spin text-primary" aria-hidden />
        </div>
      </AppPage>
    )
  }

  if (error || !agent) {
    const notFound = error instanceof ApiError && error.status === 404
    return (
      <AppPage title="Agent workspace">
        <div className="space-y-4">
          <Alert>{notFound ? "This agent doesn't exist or you don't have access to it." : "Couldn't load this agent."}</Alert>
          <BackLink />
        </div>
      </AppPage>
    )
  }

  const facts = [
    ["Primary user", agent.primary_user],
    ["Reviewer", agent.reviewer],
    [
      "Your access",
      agent.my_capacities.length
        ? agent.my_capacities.map((c) => CAPACITY_LABELS[c]).join(", ")
        : "Finance Admin oversight",
    ],
  ]

  return (
    <AppPage
      title={agent.name}
      subtitle="Complete the input form and attach supporting documents (workspace coming soon)."
    >
      <div className="max-w-3xl space-y-5">
        <BackLink />
        <section className="rounded-lg border bg-card p-6">
          <p className="text-[15px] leading-relaxed">{agent.description}</p>
          <dl className="mt-5 grid gap-4 sm:grid-cols-3">
            {facts.map(([label, value]) => (
              <div key={label}>
                <dt className="text-xs font-semibold tracking-wide text-muted-foreground uppercase">{label}</dt>
                <dd className="mt-1 font-medium">{value}</dd>
              </div>
            ))}
          </dl>
        </section>
        <p className="text-sm text-muted-foreground">
          The input, validation, analysis and review screens for this agent will appear here.
        </p>
      </div>
    </AppPage>
  )
}
