import { Link, Navigate, useParams } from "react-router"
import { ArrowRight } from "lucide-react"

import { LoadError, Loading } from "./components/bits"
import { FLOW_UI } from "./flows"
import { useWorkflows } from "./hooks"
import { WORKFLOW_SLUG, workflowFromSlug } from "./labels"

/** One card per workflow that has its screens (where its cases start); the rest are listed
 *  as coming. */
export function WorkflowCards() {
  const { data: workflows = [], isPending, isError } = useWorkflows()
  const built = workflows.filter((w) => FLOW_UI[w.key]?.home)
  const coming = workflows.filter((w) => !FLOW_UI[w.key]?.home)

  return (
    <>
      {isPending && <Loading what="workflows" />}
      {isError && <LoadError what="workflows" />}
      <ul className={`grid gap-4 md:grid-cols-2 ${built.length > 2 ? "xl:grid-cols-3" : ""}`}>
        {built.map((w) => {
          const flow = FLOW_UI[w.key]
          return (
            <li key={w.key}>
              <Link
                to={`/pod/${WORKFLOW_SLUG[w.key]}`}
                title={w.description}
                className="group flex h-full flex-col rounded-lg border bg-card p-5 transition-colors hover:border-primary/50"
              >
                <p className="font-semibold text-brand-navy">{w.name}</p>
                {flow?.Stats && (
                  <div className="mt-3 flex-1">
                    <flow.Stats />
                  </div>
                )}
                {flow?.home && (
                  <span className="mt-4 inline-flex items-center gap-1.5 self-start rounded-md bg-primary px-3 py-1.5 text-sm font-medium text-primary-foreground transition-colors group-hover:bg-primary/90">
                    Open {flow.home.label} to start a case
                    <ArrowRight className="size-4 transition-transform group-hover:translate-x-0.5" aria-hidden />
                  </span>
                )}
              </Link>
            </li>
          )
        })}
      </ul>
      {coming.length > 0 && (
        <p className="mt-3 text-xs text-muted-foreground">Coming soon: {coming.map((w) => w.name).join(" · ")}</p>
      )}
    </>
  )
}

/** /pod/<slug>: the workflow's own home screen, or its cases when it has none yet. */
export function WorkflowHomePage() {
  const { slug } = useParams()
  const key = workflowFromSlug(slug)
  if (!key) return <Navigate to="/pod" replace />
  const Home = FLOW_UI[key]?.home?.Page
  return Home ? <Home /> : <Navigate to={`/pod/cases?workflow=${slug}`} replace />
}
