import { Link, Navigate, useParams } from "react-router"
import { ArrowRight } from "lucide-react"

import { AppPage } from "@/components/layout/app-page"
import { useCurrentUser } from "@/features/auth/hooks"
import { isAdmin } from "@/features/auth/roles"

import { Empty, LoadError, Loading, PodTabs } from "./components/bits"
import { FLOW_UI } from "./flows"
import { useWorkflows } from "./hooks"
import { WORKFLOW_SLUG, workflowFromSlug } from "./labels"

/** Service POD home: one card per workflow the viewer works in (deck slide 2). */
export function WorkflowsPage() {
  const { data: user } = useCurrentUser()
  const { data: workflows, isPending, isError } = useWorkflows()
  const admin = isAdmin(user)
  // Role-filtered: a Finance Admin oversees all five; others see the ones they have a role in
  const visible = (workflows ?? []).filter((w) => admin || w.my_capacities.length > 0)

  return (
    <AppPage title="Service POD" subtitle="Five governed finance workflows on read-only QuickBooks data. Finance Admin posts manually.">
      <PodTabs />
      {isPending && <Loading what="workflows" />}
      {isError && <LoadError what="workflows" />}
      {workflows && visible.length === 0 && (
        <Empty>You have no role in a Service POD workflow yet. Ask a Finance Admin to assign one.</Empty>
      )}
      <ul className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
        {visible.map((w) => {
          const flow = FLOW_UI[w.key]
          const roles = w.my_capacities.map((c) => w.labels[c] ?? c)
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
                <div className="mt-4 border-t pt-3">
                  {flow?.Stats ? <flow.Stats /> : <p className="text-xs text-muted-foreground">Its own screens come next; cases can already be opened.</p>}
                </div>
                <p className="mt-3 text-xs">{roles.length ? `You: ${roles.join(", ")}` : "Oversight (read only)"}</p>
              </Link>
            </li>
          )
        })}
      </ul>
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
