import { Link, useNavigate, useParams } from "react-router"
import { ArrowLeft, Inbox, LoaderCircle, Plus } from "lucide-react"
import { toast } from "sonner"

import { AppPage } from "@/components/layout/app-page"
import { Alert } from "@/components/ui/alert"
import { Button } from "@/components/ui/button"
import { ApiError } from "@/lib/api"

import type { AgentCapacity } from "../api"
import { useAgent } from "../hooks"
import type { RunSummary } from "./api"
import { StatusBadge } from "./components/status-badge"
import { formatDateTime } from "./format"
import { useCreateRun, useRuns } from "./hooks"

const CAPACITY_LABELS: Record<AgentCapacity, string> = { preparer: "Preparer", reviewer: "Reviewer" }

function BackLink() {
  return (
    <Link to="/catalog" className="inline-flex items-center gap-1.5 text-sm font-medium text-primary hover:underline">
      <ArrowLeft className="size-4" aria-hidden />
      Back to catalog
    </Link>
  )
}

function RunsTable({ agentKey, runs }: { agentKey: string; runs: RunSummary[] }) {
  if (!runs.length) {
    return (
      <div className="flex flex-col items-center gap-2 py-10 text-center">
        <Inbox className="size-7 text-muted-foreground" aria-hidden />
        <p className="font-medium">No runs yet</p>
        <p className="text-sm text-muted-foreground">Analyses started for this agent will be listed here.</p>
      </div>
    )
  }
  return (
    <div className="overflow-x-auto">
      <table className="w-full min-w-[640px] text-sm">
        <thead>
          <tr className="border-b text-left text-xs tracking-wide text-muted-foreground uppercase">
            <th className="py-2 pr-4 font-semibold">Run</th>
            <th className="py-2 pr-4 font-semibold">Reference</th>
            <th className="py-2 pr-4 font-semibold">Result</th>
            <th className="py-2 pr-4 font-semibold">Preparer</th>
            <th className="py-2 pr-4 font-semibold">Updated</th>
            <th className="py-2 font-semibold">Status</th>
          </tr>
        </thead>
        <tbody className="divide-y">
          {runs.map((run) => (
            <tr key={run.id} className="hover:bg-secondary/40">
              <td className="py-3 pr-4">
                <Link to={`/catalog/${agentKey}/runs/${run.id}`} className="font-semibold text-primary hover:underline">
                  {run.reference}
                </Link>
              </td>
              <td className="py-3 pr-4">{run.business_reference ?? "—"}</td>
              <td className="py-3 pr-4">
                {run.headline ?? <span className="text-muted-foreground">Not analyzed</span>}
                {run.priority === "high" && <span className="ml-2 text-xs font-semibold text-red-700">High priority</span>}
              </td>
              <td className="py-3 pr-4">{run.preparer.full_name}</td>
              <td className="py-3 pr-4 whitespace-nowrap text-muted-foreground">{formatDateTime(run.updated_at)}</td>
              <td className="py-3">
                <StatusBadge status={run.status} label={run.status_label} />
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

/** Agent home: what it does, who prepares/reviews, run history and "New analysis". */
export function WorkspacePage() {
  const { agentKey = "" } = useParams()
  const navigate = useNavigate()
  const { data: agent, isPending, error } = useAgent(agentKey)
  const runs = useRuns(agentKey, Boolean(agent?.has_workspace))
  const create = useCreateRun(agentKey)

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

  const canPrepare = agent.has_workspace && agent.is_active && agent.my_capacities.includes("preparer")
  const startRun = () =>
    create.mutate(undefined, {
      onSuccess: (run) => void navigate(`/catalog/${agentKey}/runs/${run.id}`),
      onError: (e) => toast.error(e instanceof ApiError ? e.message : "Couldn't start a new analysis"),
    })

  const facts = [
    ["Primary user", agent.primary_user],
    ["Reviewer", agent.reviewer],
    [
      "Your access",
      agent.my_capacities.length ? agent.my_capacities.map((c) => CAPACITY_LABELS[c]).join(", ") : "Finance Admin oversight",
    ],
  ]

  return (
    <AppPage title={agent.name} subtitle={agent.description}>
      <div className="space-y-5">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <BackLink />
          {canPrepare && (
            <Button onClick={startRun} disabled={create.isPending}>
              <Plus aria-hidden />
              {create.isPending ? "Starting…" : "New analysis"}
            </Button>
          )}
        </div>

        <section className="rounded-lg border bg-card p-5 sm:p-6">
          <dl className="grid gap-4 sm:grid-cols-3">
            {facts.map(([label, value]) => (
              <div key={label}>
                <dt className="text-xs font-semibold tracking-wide text-muted-foreground uppercase">{label}</dt>
                <dd className="mt-1 font-medium">{value}</dd>
              </div>
            ))}
          </dl>
        </section>

        {!agent.has_workspace ? (
          <p className="rounded-lg border border-dashed bg-card px-6 py-10 text-center text-sm text-muted-foreground">
            The workspace for this agent is coming soon.
          </p>
        ) : (
          <section className="rounded-lg border bg-card p-5 sm:p-6" aria-labelledby="runs-title">
            <h2 id="runs-title" className="border-b pb-4 text-lg font-semibold text-brand-navy">
              Run history
            </h2>
            {runs.isPending ? (
              <div className="flex justify-center py-10" role="status">
                <LoaderCircle className="size-5 animate-spin text-primary" aria-hidden />
              </div>
            ) : runs.isError ? (
              <Alert className="mt-4">Couldn't load the run history.</Alert>
            ) : (
              <RunsTable agentKey={agentKey} runs={runs.data} />
            )}
          </section>
        )}
      </div>
    </AppPage>
  )
}
