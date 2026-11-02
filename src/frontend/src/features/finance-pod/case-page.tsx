import { useParams } from "react-router"
import { CircleAlert, CircleCheck } from "lucide-react"
import { toast } from "sonner"

import { Card, GuardedButton, LoadError, Loading } from "@/features/service-pod/components/bits"
import { errorMessage } from "@/lib/api"
import { cn } from "@/lib/utils"

import { useCaseAction, useFinanceCase, useFinanceWorkflows } from "./hooks"
import { CASE_STATUS, capacityLabel, KIND_META } from "./labels"
import { FinancePage } from "./components/finance-page"
import { StepCard } from "./components/step-card"

function Legend() {
  return (
    <ul className="flex flex-wrap gap-3 text-xs text-muted-foreground" aria-label="Step colours">
      {(["agent", "person", "system"] as const).map((kind) => (
        <li key={kind} className="flex items-center gap-1.5">
          <span className={cn("inline-block size-3 rounded-sm", KIND_META[kind].chip)} />
          {KIND_META[kind].label}
        </li>
      ))}
    </ul>
  )
}

export function FinanceCasePage() {
  const { caseId } = useParams()
  const { data: c, isLoading, isError } = useFinanceCase(caseId)
  const workflows = useFinanceWorkflows()
  const action = useCaseAction()

  if (isLoading) return <FinancePage title="Case"><Loading what="the case" /></FinancePage>
  if (isError || !c) return <FinancePage title="Case"><LoadError what="the case" /></FinancePage>

  const workflow = workflows.data?.find((w) => w.key === c.workflow)
  const current = c.steps.find((s) => s.status === "pending" || s.status === "failed")?.key
  const approve = () =>
    action.mutate(
      { id: c.id, version: c.version, action: "approve" },
      {
        onSuccess: () => toast.success(c.next_signoff ? `Signed off as ${capacityLabel(c.next_signoff)}` : "Approved"),
        onError: (error) => toast.error(errorMessage(error, "Couldn't approve.")),
      },
    )

  return (
    <FinancePage title={`${c.reference} · ${c.title}`} subtitle={`${workflow?.name ?? c.workflow} · ${c.entity.code} · opened by ${c.owner.name}`}>
      <div className="grid gap-4 lg:grid-cols-[1fr_320px]">
        <Card title="Steps" hint="The requirement's L4 tasks in order, each with its L5 steps." actions={<Legend />}>
          <div className="space-y-3">
            {c.steps.map((step) => (
              <StepCard key={step.key} c={c} step={step} open={step.key === current} />
            ))}
          </div>
        </Card>

        <div className="space-y-4">
          <Card title="Status">
            <span className={cn("rounded-full px-2 py-0.5 text-xs font-medium", CASE_STATUS[c.status].className)}>
              {CASE_STATUS[c.status].label}
            </span>
            {c.blockers.length > 0 ? (
              <ul className="mt-3 space-y-1.5 text-sm">
                {c.blockers.map((b) => (
                  <li key={b} className="flex gap-2">
                    <CircleAlert className="mt-0.5 size-4 shrink-0 text-amber-600" aria-hidden />
                    {b}
                  </li>
                ))}
              </ul>
            ) : (
              c.status === "draft" && (
                <p className="mt-3 flex gap-2 text-sm">
                  <CircleCheck className="mt-0.5 size-4 shrink-0 text-emerald-600" aria-hidden />
                  Every step is settled.
                </p>
              )
            )}
            {c.status === "draft" && c.next_signoff && (
              <div className="mt-3">
                <GuardedButton reason={c.allowed_actions.approve} onClick={approve} disabled={action.isPending}>
                  Sign off as {capacityLabel(c.next_signoff)}
                </GuardedButton>
              </div>
            )}
          </Card>

          <Card title="Sign-offs" hint={workflow ? `Needed: ${workflow.signoffs.map((s) => capacityLabel(s)).join(", then ")}` : undefined}>
            {c.approvals.length === 0 ? (
              <p className="text-sm text-muted-foreground">None yet.</p>
            ) : (
              <ul className="space-y-1 text-sm">
                {c.approvals.map((a) => (
                  <li key={a.id} className={cn(!a.valid && "text-muted-foreground line-through")}>
                    {capacityLabel(a.capacity)}: {a.user.name}
                    <span className="block text-xs text-muted-foreground">
                      {new Date(a.created_at).toLocaleString()}
                      {!a.valid && " · content changed since"}
                    </span>
                  </li>
                ))}
              </ul>
            )}
          </Card>

          {c.review_tasks.length > 0 && (
            <Card title="Review tasks">
              <ul className="space-y-2 text-sm">
                {c.review_tasks.map((t) => (
                  <li key={t.id}>
                    <span className="font-medium">{t.kind.replace(/_/g, " ")}</span>
                    {t.subject && ` · ${t.subject}`}
                    <p className="text-xs text-muted-foreground">{t.detail}</p>
                    {t.status === "resolved" && <p className="text-xs">Resolved: {t.resolution}</p>}
                  </li>
                ))}
              </ul>
            </Card>
          )}
        </div>
      </div>
    </FinancePage>
  )
}
