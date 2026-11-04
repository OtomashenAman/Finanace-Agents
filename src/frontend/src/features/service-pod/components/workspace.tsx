import type { ReactNode } from "react"
import { Link, NavLink } from "react-router"
import { ChevronRight } from "lucide-react"

import { cn } from "@/lib/utils"

import type { WorkflowKey } from "../api"
import { useWorkflows } from "../hooks"
import { WORKFLOW_SHORT, WORKFLOW_SLUG } from "../labels"
import { PodTabs } from "./bits"
import { PodPage } from "./pod-page"

interface WorkflowWorkspaceProps {
  workflow: WorkflowKey
  /** Label of the workflow's own home screen (Portfolio, Unapplied cash...); none: cases only */
  homeLabel?: string
  children: ReactNode
}

const subTab = ({ isActive }: { isActive: boolean }) =>
  cn(
    "rounded-md px-3 py-1.5 text-sm font-medium transition-colors",
    isActive ? "bg-primary/10 text-primary" : "text-muted-foreground hover:bg-secondary hover:text-foreground",
  )

/** One workflow's workspace: Workflows › name, and its own screens (home, cases). */
export function WorkflowWorkspace({ workflow, homeLabel, children }: WorkflowWorkspaceProps) {
  const { data: workflows } = useWorkflows()
  const spec = workflows?.find((w) => w.key === workflow)
  const slug = WORKFLOW_SLUG[workflow]
  return (
    <PodPage title={spec?.name ?? WORKFLOW_SHORT[workflow]} subtitle={spec?.description}>
      <PodTabs />
      <div className="mb-5 flex flex-wrap items-center justify-between gap-3">
        <p className="flex items-center gap-1 text-sm">
          <Link to="/pod" className="text-muted-foreground hover:text-foreground">
            Dashboard
          </Link>
          <ChevronRight className="size-3.5 text-muted-foreground" aria-hidden />
          <span className="font-semibold text-brand-navy">{spec?.name ?? WORKFLOW_SHORT[workflow]}</span>
        </p>
        <nav aria-label={`${spec?.name ?? WORKFLOW_SHORT[workflow]} screens`} className="flex gap-1.5">
          {homeLabel && (
            <NavLink to={`/pod/${slug}`} end className={subTab}>
              {homeLabel}
            </NavLink>
          )}
          <NavLink to={`/pod/${slug}/cases`} className={subTab}>
            Cases
          </NavLink>
        </nav>
      </div>
      {children}
    </PodPage>
  )
}
