import { Link, Navigate, useParams } from "react-router"
import { ArrowRight } from "lucide-react"

import { LivePulse, LoadError, Loading } from "./components/bits"
import { FLOW_UI } from "./flows"
import { useWorkflows } from "./hooks"
import { AI_AGENTS, WORKFLOW_SLUG, workflowFromSlug } from "./labels"

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
          const agent = AI_AGENTS[w.key]
          return (
            <li key={w.key}>
              <Link
                to={`/pod/${WORKFLOW_SLUG[w.key]}`}
                title={w.description}
                className="group relative flex h-full flex-col justify-between overflow-hidden rounded-xl border border-border/80 bg-card p-4.5 shadow-2xs transition-all duration-200 hover:-translate-y-1 hover:border-violet-400/80 hover:shadow-lg dark:hover:border-violet-600/60"
              >
                <div>
                  <div className="flex items-start justify-between gap-2 border-b border-border/50 pb-2.5">
                    <div className="flex items-center gap-2.5">
                      <span className="flex size-7 items-center justify-center rounded-lg bg-secondary/80 text-base shadow-2xs">
                        {agent?.avatar ?? "⚡"}
                      </span>
                      <div>
                        <p className="text-sm font-bold text-foreground group-hover:text-primary transition-colors">
                          {w.name}
                        </p>
                        <p className="text-[11px] text-muted-foreground line-clamp-1">{w.description}</p>
                      </div>
                    </div>
                    <LivePulse color="emerald" label="Online" className="text-[10px] font-semibold text-emerald-600 dark:text-emerald-400" />
                  </div>

                  {flow?.Stats && (
                    <div className="mt-3">
                      <flow.Stats />
                    </div>
                  )}
                </div>

                {flow?.home && (
                  <div className="mt-4 flex items-center justify-between border-t border-border/40 pt-2.5">
                    <span className="text-xs font-medium text-muted-foreground group-hover:text-foreground transition-colors">
                      {flow.home.label}
                    </span>
                    <span className="inline-flex items-center gap-1 text-xs font-semibold text-primary group-hover:translate-x-0.5 transition-transform">
                      Launch <ArrowRight className="size-3.5" aria-hidden />
                    </span>
                  </div>
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
