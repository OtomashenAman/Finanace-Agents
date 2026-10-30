import { Link, Navigate, useParams } from "react-router"
import { ArrowRight } from "lucide-react"

import { AppPage } from "@/components/layout/app-page"

import { LoadError, Loading, PodTabs } from "./components/bits"
import { FLOW_UI } from "./flows"
import { useWorkflows } from "./hooks"
import { WORKFLOW_SLUG, workflowFromSlug } from "./labels"

/** Service POD home: one card per workflow that has its screens (deck slide 2); the rest
 *  are listed as coming. */
export function WorkflowsPage() {
  const { data: workflows = [], isPending, isError } = useWorkflows()
  const built = workflows.filter((w) => FLOW_UI[w.key]?.home)
  const coming = workflows.filter((w) => !FLOW_UI[w.key]?.home)

  return (
    <AppPage title="Service POD" subtitle="Governed finance workflows on read-only QuickBooks data. You post in QuickBooks by hand.">
      <PodTabs />
      {isPending && <Loading what="workflows" />}
      {isError && <LoadError what="workflows" />}
      <ul className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
        {built.map((w) => {
          const flow = FLOW_UI[w.key]
          return (
            <li key={w.key}>
              <Link
                to={`/pod/${WORKFLOW_SLUG[w.key]}`}
                className="group flex h-full flex-col rounded-lg border bg-card p-5 transition-colors hover:border-primary/50 hover:bg-secondary/20"
              >
                <p className="flex items-center justify-between gap-2">
                  <span className="font-semibold text-brand-navy">{w.name}</span>
                  <ArrowRight className="size-4 text-muted-foreground transition-transform group-hover:translate-x-0.5" aria-hidden />
                </p>
                <p className="mt-1 flex-1 text-xs text-muted-foreground">{w.description}</p>
                {flow?.Stats && (
                  <div className="mt-4 border-t pt-3">
                    <flow.Stats />
                  </div>
                )}
              </Link>
            </li>
          )
        })}
      </ul>
      {coming.length > 0 && (
        <p className="mt-6 text-xs text-muted-foreground">Coming soon: {coming.map((w) => w.name).join(" · ")}</p>
      )}
    </AppPage>
  )
}

/** /pod/<slug>: the workflow's own home screen, or its cases when it has none yet. */
export function WorkflowHomePage() {
  const { slug } = useParams()
  const key = workflowFromSlug(slug)
  if (!key) return <Navigate to="/pod" replace />
  const Home = FLOW_UI[key]?.home?.Page
  return Home ? <Home /> : <Navigate to={`/pod/${slug}/cases`} replace />
}
