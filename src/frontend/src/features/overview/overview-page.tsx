import { useState } from "react"
import { LoaderCircle } from "lucide-react"

import { AppPage } from "@/components/layout/app-page"
import { Alert } from "@/components/ui/alert"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { EntitySelect } from "@/features/entities/entity-select"
import { useEntities } from "@/features/entities/hooks"
import { useAgents } from "@/features/agent-catalog/hooks"

import { AdminControlsCard } from "./components/admin-controls-card"
import { KpiCard } from "./components/kpi-card"
import { WorklistCard } from "./components/worklist-card"
import { useOverviewSummary } from "./hooks"

const FILTER =
  "flex h-10 rounded-md border border-input bg-background px-3 text-sm focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/20 focus-visible:outline-none"

function thisMonth(): string {
  const now = new Date()
  return `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, "0")}`
}

export function OverviewPage() {
  const [period, setPeriod] = useState(thisMonth)
  const [entityId, setEntityId] = useState<string | null>(null)
  const [agent, setAgent] = useState<string | null>(null)
  const [priority, setPriority] = useState<"high" | "normal" | null>(null)
  const entities = useEntities()
  const agents = useAgents()
  const { data: summary, isPending, isError, isFetching } = useOverviewSummary({ period, entityId, agent, priority })

  return (
    <AppPage
      title="Finance Operations Overview"
      subtitle="Review KPIs and open exceptions for the selected period and entity."
    >
      <div className="mb-5 flex flex-wrap items-end gap-3" aria-label="Filters" role="group">
        <div className="space-y-1.5">
          <Label htmlFor="overview-period" className="text-xs">
            Period
          </Label>
          <Input
            id="overview-period"
            type="month"
            className="h-10 w-44 text-sm"
            value={period}
            max={thisMonth()}
            onChange={(e) => e.target.value && setPeriod(e.target.value)}
          />
        </div>
        {(entities.data?.length ?? 0) > 0 && (
          <div className="space-y-1.5">
            <Label htmlFor="overview-entity" className="text-xs">
              Legal entity
            </Label>
            <EntitySelect
              id="overview-entity"
              entities={entities.data ?? []}
              value={entityId}
              onChange={setEntityId}
              allLabel="All entities"
            />
          </div>
        )}
        <div className="space-y-1.5">
          <Label htmlFor="overview-agent" className="text-xs">
            Agent
          </Label>
          <select
            id="overview-agent"
            className={FILTER}
            value={agent ?? ""}
            onChange={(e) => setAgent(e.target.value || null)}
          >
            <option value="">All agents</option>
            {agents.data?.map((a) => (
              <option key={a.key} value={a.key}>
                {a.short_name}
              </option>
            ))}
          </select>
        </div>
        <div className="space-y-1.5">
          <Label htmlFor="overview-priority" className="text-xs">
            Priority
          </Label>
          <select
            id="overview-priority"
            className={FILTER}
            value={priority ?? ""}
            onChange={(e) => setPriority((e.target.value || null) as "high" | "normal" | null)}
          >
            <option value="">Any priority</option>
            <option value="high">High</option>
            <option value="normal">Normal</option>
          </select>
        </div>
        {isFetching && !isPending && (
          <LoaderCircle className="mb-3 size-4 animate-spin text-primary" aria-label="Updating" />
        )}
      </div>
      {isPending && (
        <div className="flex justify-center py-16" role="status">
          <LoaderCircle className="size-6 animate-spin text-primary" aria-hidden />
          <span className="sr-only">Loading overview…</span>
        </div>
      )}

      {isError && <Alert>Couldn't load the overview. Refresh the page to try again.</Alert>}

      {summary && (
        <div className="space-y-6">
          <div className="grid grid-cols-2 gap-4 lg:grid-cols-4" aria-label="Key metrics">
            <KpiCard label="Active Agents" value={summary.kpis.active_agents} />
            <KpiCard label="Runs This Month" value={summary.kpis.runs_this_month} />
            <KpiCard label="Pending Review" value={summary.kpis.pending_review} />
            <KpiCard label="High Priority" value={summary.kpis.high_priority} tone="warning" />
          </div>

          <div className={summary.controls ? "grid gap-6 lg:grid-cols-[1.45fr_1fr]" : undefined}>
            <WorklistCard items={summary.worklist} />
            {summary.controls && <AdminControlsCard controls={summary.controls} />}
          </div>
        </div>
      )}
    </AppPage>
  )
}
