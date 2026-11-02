import { useState } from "react"
import { Link, Navigate, useNavigate, useParams, useSearchParams } from "react-router"
import { ArrowRight, Plus, Search } from "lucide-react"

import { AppPage } from "@/components/layout/app-page"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"

import type { CaseSummary, Workflow, WorkflowKey } from "./api"
import { Card, DemoBadge, Empty, Field, LoadError, Loading, Pill, PodTabs } from "./components/bits"
import { WorkflowWorkspace } from "./components/workspace"
import { FLOW_UI } from "./flows"
import { useCases, useCreateCase, useSnapshots, useWorkflows } from "./hooks"
import { CASE_STATUS, COLLECTION_LABEL, formatDateTime, WORKFLOW_SHORT, WORKFLOW_SLUG, workflowFromSlug } from "./labels"
import { attempt, selectClass } from "./ui"

/** Opening a case by hand: only for workflows without their own home screen yet, where the
 *  case starts from a snapshot that supplies the workflow's data. */
function NewCase({ spec, onDone }: { spec: Workflow; onDone: () => void }) {
  const [snapshotId, setSnapshotId] = useState("")
  const [title, setTitle] = useState("")
  const { data: snapshots = [] } = useSnapshots()
  const create = useCreateCase()
  const navigate = useNavigate()
  const usable = snapshots.filter((s) => spec.required.every((c) => s.coverage.includes(c)))

  return (
    <form
      className="grid gap-3 sm:grid-cols-3"
      onSubmit={(e) => {
        e.preventDefault()
        void attempt(
          () => create.mutateAsync({ workflow: spec.key, snapshot_id: snapshotId, title }),
          (c) => `${c.reference} opened.`,
        ).then((c) => {
          if (c) {
            onDone()
            void navigate(`/pod/cases/${c.id}`)
          }
        })
      }}
    >
      <Field label="Source snapshot" hint={`Needs: ${spec.required.map((c) => COLLECTION_LABEL[c]).join(", ")}`}>
        <select className={selectClass} value={snapshotId} onChange={(e) => setSnapshotId(e.target.value)}>
          <option value="">{usable.length ? "Choose…" : "No snapshot supplies all of it"}</option>
          {usable.map((s) => (
            <option key={s.id} value={s.id}>
              {s.company_name} · {s.entity.code} · as of {s.as_of}
              {s.is_demo ? " · DEMO" : ""}
            </option>
          ))}
        </select>
      </Field>
      <Field label="Title" hint="e.g. the period or the report">
        <Input value={title} maxLength={200} onChange={(e) => setTitle(e.target.value)} />
      </Field>
      <div className="flex items-end">
        <Button type="submit" size="sm" disabled={!snapshotId || !title.trim() || create.isPending}>
          Open case
        </Button>
      </div>
    </form>
  )
}

type StatusFilter = "open" | "closed" | "all"

const STATUS_FILTER: Record<StatusFilter, { label: string; match: (c: CaseSummary) => boolean }> = {
  open: { label: "Open", match: (c) => c.status === "draft" || c.status === "approved" },
  closed: { label: "Closed", match: (c) => c.status === "completed" || c.status === "cancelled" },
  all: { label: "All", match: () => true },
}

const chip = (on: boolean) =>
  `rounded-full border px-3 py-1 text-xs font-medium transition-colors ${on ? "border-primary bg-primary/10 text-primary" : "bg-card text-muted-foreground hover:text-foreground"}`

/** Where an open case stands, from its step and open review tasks (the case page says more). */
function whereItStands(c: CaseSummary): [string, Parameters<typeof Pill>[0]["tone"]] {
  if (c.status !== "draft") return CASE_STATUS[c.status]
  // The step says where the work is; open tasks may be non-blocking questions (shown beside)
  const step = FLOW_UI[c.workflow]?.steps?.find((s) => s.key === c.stage)
  if (step) return [step.label, "info"]
  return c.open_review_tasks > 0 ? ["Needs review", "warn"] : CASE_STATUS.draft
}

/** Starting a case: AR and Bank start from their own screen (the right customer or receipt);
 *  the others from a snapshot. */
function StartCase({ workflows }: { workflows: Workflow[] }) {
  const [open, setOpen] = useState(false)
  const [manual, setManual] = useState<Workflow | null>(null)
  return (
    <div className="relative">
      <Button size="sm" onClick={() => setOpen((v) => !v)}>
        <Plus /> Start a case
      </Button>
      {open && (
        <div className="absolute right-0 z-10 mt-2 w-72 rounded-lg border bg-card p-2 shadow-lg">
          {workflows.map((w) => {
            const home = FLOW_UI[w.key]?.home
            return home ? (
              <Link
                key={w.key}
                to={`/pod/${WORKFLOW_SLUG[w.key]}`}
                className="flex items-center justify-between rounded px-3 py-2 text-sm hover:bg-secondary"
              >
                <span>
                  <span className="font-medium">{w.name}</span>
                  <span className="block text-xs text-muted-foreground">from {home.label}</span>
                </span>
                <ArrowRight className="size-4 text-muted-foreground" aria-hidden />
              </Link>
            ) : (
              <button
                key={w.key}
                type="button"
                className="block w-full rounded px-3 py-2 text-left text-sm hover:bg-secondary"
                onClick={() => {
                  setManual(w)
                  setOpen(false)
                }}
              >
                <span className="font-medium">{w.name}</span>
                <span className="block text-xs text-muted-foreground">from a source snapshot</span>
              </button>
            )
          })}
        </div>
      )}
      {manual && (
        <div className="fixed inset-0 z-20 flex items-start justify-center bg-black/30 p-4 pt-24" onClick={() => setManual(null)}>
          <div className="w-full max-w-3xl rounded-lg border bg-card p-5" onClick={(e) => e.stopPropagation()}>
            <p className="mb-3 font-semibold text-brand-navy">New {manual.name} case</p>
            <NewCase spec={manual} onDone={() => setManual(null)} />
          </div>
        </div>
      )}
    </div>
  )
}

function CaseTable({
  cases,
  showWorkflow = false,
}: {
  cases: CaseSummary[]
  showWorkflow?: boolean
}) {
  if (cases.length === 0) {
    return <Empty>No cases match this filter.</Empty>
  }
  return (
    <div className="overflow-x-auto">
      <table className="w-full min-w-[640px] text-sm">
        <thead>
          <tr className="border-b text-left text-xs tracking-wide text-muted-foreground uppercase">
            <th className="py-2 pr-3 font-semibold">Case</th>
            {showWorkflow && <th className="py-2 pr-3 font-semibold">Workflow</th>}
            <th className="py-2 pr-3 font-semibold">Where it stands</th>
            <th className="py-2 pr-3 font-semibold">Entity</th>
            <th className="py-2 font-semibold">Updated</th>
          </tr>
        </thead>
        <tbody className="divide-y">
          {cases.map((c) => {
            const [label, tone] = whereItStands(c)
            return (
              <tr key={c.id} className="hover:bg-secondary/40 transition-colors">
                <td className="py-2.5 pr-3">
                  <Link to={`/pod/cases/${c.id}`} className="font-semibold text-primary hover:underline">
                    {c.reference}
                  </Link>
                  <span className="ml-2 font-medium">{c.title}</span>
                  {c.is_demo && (
                    <span className="ml-2">
                      <DemoBadge />
                    </span>
                  )}
                </td>
                {showWorkflow && (
                  <td className="py-2.5 pr-3 text-xs">
                    <Link
                      to={`/pod/${WORKFLOW_SLUG[c.workflow]}/cases`}
                      className="text-muted-foreground hover:text-foreground hover:underline font-medium"
                    >
                      {WORKFLOW_SHORT[c.workflow]}
                    </Link>
                  </td>
                )}
                <td className="py-2.5 pr-3">
                  <Pill label={label} tone={tone} />
                  {c.open_review_tasks > 0 && (
                    <span className="ml-2 text-xs font-medium text-amber-700 dark:text-amber-400">
                      {c.open_review_tasks} open task{c.open_review_tasks > 1 ? "s" : ""}
                    </span>
                  )}
                </td>
                <td className="py-2.5 pr-3 text-xs font-mono">{c.entity.code}</td>
                <td className="py-2.5 text-xs text-muted-foreground">{formatDateTime(c.updated_at)}</td>
              </tr>
            )
          })}
        </tbody>
      </table>
    </div>
  )
}

/** Every case, grouped and categorized by workflow: filter by category, open/closed, step, or search. */
export function CasesPage() {
  const [params, setParams] = useSearchParams()
  const { data: workflows = [] } = useWorkflows()
  const cases = useCases({})
  const workflow = workflowFromSlug(params.get("workflow") ?? undefined)
  const status = (params.get("status") as StatusFilter | null) ?? "open"
  const stage = params.get("stage")
  const [q, setQ] = useState("")

  const set = (key: string, value: string | null) => {
    const next = new URLSearchParams(params)
    if (value) next.set(key, value)
    else next.delete(key)
    if (key === "workflow") next.delete("stage")
    setParams(next, { replace: true })
  }
  const used = workflows.filter((w) => (cases.data ?? []).some((c) => c.workflow === w.key))
  const steps = workflow ? (FLOW_UI[workflow]?.steps ?? []) : []
  const stepLabel = stage ? steps.find((s) => s.key === stage)?.label : undefined
  const needle = q.trim().toLowerCase()
  const rows = (cases.data ?? []).filter(
    (c) =>
      (!workflow || c.workflow === workflow) &&
      STATUS_FILTER[status].match(c) &&
      (!stage || c.stage === stage) &&
      (!needle || `${c.reference} ${c.title}`.toLowerCase().includes(needle)),
  )
  const countFor = (key: WorkflowKey | null) =>
    (cases.data ?? []).filter((c) => (!key || c.workflow === key) && STATUS_FILTER[status].match(c)).length

  return (
    <AppPage title="Service POD" subtitle="Cases categorized by workflow. Track progress, steps, and required sign-offs.">
      <PodTabs />
      <div className="space-y-6">
        <Card
          title="Cases Directory"
          hint="Categorized by workflow. Filter by category or search across all workflows."
          actions={<StartCase workflows={workflows.filter((w) => FLOW_UI[w.key])} />}
        >
          <div className="flex flex-col gap-3 lg:flex-row lg:items-center lg:justify-between">
            <div className="flex flex-wrap gap-1.5" role="group" aria-label="Workflow Categories">
              <button
                type="button"
                className={chip(!workflow)}
                onClick={() => set("workflow", null)}
              >
                All Categories ({countFor(null)})
              </button>
              {used.map((w) => (
                <button
                  key={w.key}
                  type="button"
                  className={chip(workflow === w.key)}
                  onClick={() => set("workflow", WORKFLOW_SLUG[w.key])}
                >
                  {w.name} ({countFor(w.key)})
                </button>
              ))}
            </div>
            <div className="flex flex-wrap items-center gap-2">
              <div className="flex gap-1" role="group" aria-label="Status">
                {(Object.keys(STATUS_FILTER) as StatusFilter[]).map((k) => (
                  <button
                    key={k}
                    type="button"
                    className={chip(status === k)}
                    onClick={() => set("status", k === "open" ? null : k)}
                  >
                    {STATUS_FILTER[k].label}
                  </button>
                ))}
              </div>
              <div className="relative">
                <Search className="absolute top-1/2 left-2.5 size-4 -translate-y-1/2 text-muted-foreground" aria-hidden />
                <Input
                  className="h-8 w-52 pl-8"
                  placeholder="Search case or customer…"
                  value={q}
                  onChange={(e) => setQ(e.target.value)}
                />
              </div>
            </div>
          </div>
          {stepLabel && (
            <p className="mt-3 flex items-center gap-2 text-sm border-t pt-2.5">
              Filtered by step: <Pill label={stepLabel} tone="info" />
              <button
                type="button"
                className="text-xs text-primary hover:underline"
                onClick={() => set("stage", null)}
              >
                clear
              </button>
            </p>
          )}
        </Card>

        {cases.isPending && <Loading what="cases" />}
        {cases.isError && <LoadError what="cases" />}

        {/* When a specific workflow category is selected */}
        {workflow && (
          <Card
            title={`${WORKFLOW_SHORT[workflow]} Cases (${rows.length})`}
            hint={workflows.find((w) => w.key === workflow)?.description}
            actions={
              <Link
                to={`/pod/${WORKFLOW_SLUG[workflow]}`}
                className="text-xs font-semibold text-primary hover:underline"
              >
                Open {WORKFLOW_SHORT[workflow]} Workspace →
              </Link>
            }
          >
            <CaseTable cases={rows} />
          </Card>
        )}

        {/* When All Categories is selected: group clearly by workflow category cards */}
        {!workflow && cases.data && (
          <div className="space-y-6">
            {used.map((w) => {
              const flowCases = rows.filter((c) => c.workflow === w.key)
              if (flowCases.length === 0 && q) return null
              const flow = FLOW_UI[w.key]
              const slug = WORKFLOW_SLUG[w.key]
              return (
                <Card
                  key={w.key}
                  title={`${w.name} (${flowCases.length})`}
                  hint={w.description}
                  actions={
                    <div className="flex items-center gap-3">
                      {flow?.home && (
                        <Link
                          to={`/pod/${slug}`}
                          className="text-xs text-muted-foreground hover:text-foreground hover:underline"
                        >
                          {flow.home.label} →
                        </Link>
                      )}
                      <Link
                        to={`/pod/${slug}/cases`}
                        className="rounded border border-border/80 px-2.5 py-1 text-xs font-semibold text-primary hover:bg-secondary/60 transition-colors"
                      >
                        View {WORKFLOW_SHORT[w.key]} workspace →
                      </Link>
                    </div>
                  }
                >
                  <CaseTable cases={flowCases} />
                </Card>
              )
            })}
          </div>
        )}
      </div>
    </AppPage>
  )
}

/** /pod/<slug>/cases: cases of this specific workflow, rendered inside its own WorkflowWorkspace. */
export function LegacyWorkflowCases() {
  const { slug } = useParams()
  const key = workflowFromSlug(slug)
  if (!key) return <Navigate to="/pod" replace />

  const { data: workflows = [] } = useWorkflows()
  const spec = workflows.find((w) => w.key === key)
  const flow = FLOW_UI[key]
  const cases = useCases({ workflow: key })
  const [status, setStatus] = useState<StatusFilter>("open")
  const [q, setQ] = useState("")

  const needle = q.trim().toLowerCase()
  const rows = (cases.data ?? []).filter(
    (c) =>
      STATUS_FILTER[status].match(c) &&
      (!needle || `${c.reference} ${c.title}`.toLowerCase().includes(needle)),
  )

  return (
    <WorkflowWorkspace workflow={key} homeLabel={flow?.home?.label}>
      <Card
        title={`${spec?.name ?? WORKFLOW_SHORT[key]} Cases (${rows.length})`}
        hint={`Track all cases, steps, and sign-offs for ${spec?.name ?? WORKFLOW_SHORT[key]}.`}
        actions={flow?.home ? (
          <Link to={`/pod/${slug}`}>
            <Button size="sm" variant="outline">
              <Plus /> Open from {flow.home.label}
            </Button>
          </Link>
        ) : undefined}
      >
        <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
          <div className="flex gap-1" role="group" aria-label="Status">
            {(Object.keys(STATUS_FILTER) as StatusFilter[]).map((k) => (
              <button
                key={k}
                type="button"
                className={chip(status === k)}
                onClick={() => setStatus(k)}
              >
                {STATUS_FILTER[k].label} ({(cases.data ?? []).filter((c) => STATUS_FILTER[k].match(c)).length})
              </button>
            ))}
          </div>
          <div className="relative">
            <Search className="absolute top-1/2 left-2.5 size-4 -translate-y-1/2 text-muted-foreground" aria-hidden />
            <Input className="h-8 w-52 pl-8" placeholder="Search case…" value={q} onChange={(e) => setQ(e.target.value)} />
          </div>
        </div>

        {cases.isPending && <Loading what="cases" />}
        {cases.isError && <LoadError what="cases" />}
        <CaseTable cases={rows} />
      </Card>
    </WorkflowWorkspace>
  )
}
