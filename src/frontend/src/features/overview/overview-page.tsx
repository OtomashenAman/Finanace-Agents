import { LoaderCircle } from "lucide-react"

import { AppPage } from "@/components/layout/app-page"
import { Alert } from "@/components/ui/alert"

import { AdminControlsCard } from "./components/admin-controls-card"
import { KpiCard } from "./components/kpi-card"
import { WorklistCard } from "./components/worklist-card"
import { useOverviewSummary } from "./hooks"

export function OverviewPage() {
  const { data: summary, isPending, isError } = useOverviewSummary()

  return (
    <AppPage
      title="Finance Operations Overview"
      subtitle="Review KPIs and open exceptions for the selected period and entity."
    >
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
