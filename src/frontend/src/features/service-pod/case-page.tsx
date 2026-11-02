import { Link, useParams } from "react-router"
import { ArrowLeft, ChevronRight } from "lucide-react"

import { AppPage } from "@/components/layout/app-page"

import type { CaseDetail } from "./api"
import { DemoBadge, LoadError, Loading, Pill, PodTabs } from "./components/bits"
import { CaseAudit, CaseData, PostingTasks } from "./components/case-extras"
import { Artifacts, Messages } from "./components/case-messages"
import { Commitments, Decisions, OwnedActions, ReviewTasks } from "./components/case-sections"
import { CaseSteps } from "./components/case-steps"
import { RefreshSource } from "./components/refresh-source"
import { RelatedCases } from "./components/related-cases"
import { FLOW_UI } from "./flows"
import { useCase } from "./hooks"
import type { NextAction } from "./flows/types"
import { CASE_PHASE, CASE_STATUS, formatDateTime, WORKFLOW_SHORT, WORKFLOW_SLUG } from "./labels"

function Header({ c, next }: { c: CaseDetail; next?: NextAction }) {
  // Workflows with steps say where the work stands; others show the case's own status
  const [label, tone] = next ? CASE_PHASE[next.phase] : CASE_STATUS[c.status]
  return (
    <div className="rounded-lg border bg-card px-5 py-4">
      <p className="mb-1.5 flex items-center gap-1 text-xs text-muted-foreground">
        <Link to="/pod/cases" className="inline-flex items-center gap-1 hover:text-foreground">
          <ArrowLeft className="size-3" aria-hidden /> Cases
        </Link>
        <ChevronRight className="size-3" aria-hidden />
        <Link to={`/pod/cases?workflow=${WORKFLOW_SLUG[c.workflow]}`} className="hover:text-foreground">
          {WORKFLOW_SHORT[c.workflow]}
        </Link>
      </p>
      <p className="flex flex-wrap items-center gap-2">
        <span className="text-lg font-bold text-brand-navy">{c.reference}</span>
        <span className="text-lg">{c.title}</span>
        <Pill label={label} tone={tone} />
        {c.is_demo && <DemoBadge />}
      </p>
      <p className="mt-1 text-xs text-muted-foreground">
        {c.entity.code} · opened by {c.owner.name} · data from {c.snapshot.company_name} as of {c.snapshot.as_of}
      </p>
    </div>
  )
}

/** One case: its source, content, people and every decision on it. Workflows with steps show
 *  one deck screen at a time; others show every section. */
export function CasePage() {
  const { caseId } = useParams()
  const { data: c, isPending, isError } = useCase(caseId)
  const flow = c ? FLOW_UI[c.workflow] : undefined
  const next = c && flow?.steps && flow.nextAction ? flow.nextAction(c) : undefined
  return (
    <AppPage title="Service POD" subtitle={c ? `${c.reference} · updated ${formatDateTime(c.updated_at)}` : undefined}>
      <PodTabs />
      {isPending && <Loading what="the case" />}
      {isError && <LoadError what="this case (it may not exist or isn't yours)" />}
      {c && (
        <div className="space-y-5">
          <Header c={c} next={next} />
          <RefreshSource c={c} />
          {flow?.steps && next ? (
            <CaseSteps key={c.id} c={c} steps={flow.steps} next={next} ownsPosting={flow.ownsPosting} aside={<RelatedCases c={c} />} />
          ) : (
            <div className="grid gap-6 xl:grid-cols-[minmax(0,1fr)_360px]">
              <div className="space-y-6">
                {flow?.CasePanel && <flow.CasePanel c={c} />}
                <ReviewTasks c={c} />
                <Messages c={c} purposes={flow?.purposes} ReplyPanel={flow?.ReplyPanel} />
                {(flow?.showsCommitments ?? true) && <Commitments c={c} />}
                <OwnedActions c={c} />
                <Artifacts c={c} />
                {!flow?.ownsPosting && <PostingTasks c={c} />}
                <CaseData c={c} />
                <CaseAudit c={c} />
              </div>
              <div className="space-y-6 xl:sticky xl:top-4 xl:self-start">
                <Decisions c={c} />
                <RelatedCases c={c} />
              </div>
            </div>
          )}
        </div>
      )}
    </AppPage>
  )
}
