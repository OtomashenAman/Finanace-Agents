import { useState } from "react"
import { Link, Navigate, useNavigate, useParams, useSearchParams } from "react-router"
import { ArrowRight, Plus, Search } from "lucide-react"

import { AppPage } from "@/components/layout/app-page"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"

import type { CaseSummary, Workflow, WorkflowKey } from "./api"
import { Card, DemoBadge, Empty, Field, LoadError, Loading, Pill, PodTabs } from "./components/bits"
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
  if (c.open_review_tasks > 0) return ["Needs review", "warn"]
  const step = FLOW_UI[c.workflow]?.steps?.find((s) => s.key === c.stage)
  return step ? [step.label, "info"] : CASE_STATUS.draft
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

/** Every case, all workflows: filter by workflow, open/closed, step, or search. */
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
    <AppPage title="Service POD" subtitle="Every case across the workflows.">
      <PodTabs />
      <Card title="Cases" actions={<StartCase workflows={workflows.filter((w) => FLOW_UI[w.key])} />}>
        <div className="mb-4 flex flex-col gap-3 lg:flex-row lg:items-center lg:justify-between">
          <div className="flex flex-wrap gap-1.5" role="group" aria-label="Workflow">
            <button type="button" className={chip(!workflow)} onClick={() => set("workflow", null)}>
              All workflows {countFor(null)}
            </button>
            {used.map((w) => (
              <button key={w.key} type="button" className={chip(workflow === w.key)} onClick={() => set("workflow", WORKFLOW_SLUG[w.key])}>
                {WORKFLOW_SHORT[w.key]} {countFor(w.key)}
              </button>
            ))}
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <div className="flex gap-1" role="group" aria-label="Status">
              {(Object.keys(STATUS_FILTER) as StatusFilter[]).map((k) => (
                <button key={k} type="button" className={chip(status === k)} onClick={() => set("status", k === "open" ? null : k)}>
                  {STATUS_FILTER[k].label}
                </button>
              ))}
            </div>
            <div className="relative">
              <Search className="absolute top-1/2 left-2.5 size-4 -translate-y-1/2 text-muted-foreground" aria-hidden />
              <Input className="h-8 w-52 pl-8" placeholder="Search case or customer…" value={q} onChange={(e) => setQ(e.target.value)} />
            </div>
          </div>
        </div>
        {stepLabel && (
          <p className="mb-3 flex items-center gap-2 text-sm">
            On step: <Pill label={stepLabel} tone="info" />
            <button type="button" className="text-xs text-primary hover:underline" onClick={() => set("stage", null)}>
              clear
            </button>
          </p>
        )}
        {cases.isPending && <Loading what="cases" />}
        {cases.isError && <LoadError what="cases" />}
        {cases.data && rows.length === 0 && <Empty>No case matches.</Empty>}
        {rows.length > 0 && (
          <div className="overflow-x-auto">
            <table className="w-full min-w-[640px] text-sm">
              <thead>
                <tr className="border-b text-left text-xs tracking-wide text-muted-foreground uppercase">
                  <th className="py-2 pr-3 font-semibold">Case</th>
                  <th className="py-2 pr-3 font-semibold">Workflow</th>
                  <th className="py-2 pr-3 font-semibold">Where it stands</th>
                  <th className="py-2 pr-3 font-semibold">Entity</th>
                  <th className="py-2 font-semibold">Updated</th>
                </tr>
              </thead>
              <tbody className="divide-y">
                {rows.map((c) => {
                  const [label, tone] = whereItStands(c)
                  return (
                    <tr key={c.id} className="hover:bg-secondary/40">
                      <td className="py-2.5 pr-3">
                        <Link to={`/pod/cases/${c.id}`} className="font-semibold text-primary hover:underline">
                          {c.reference}
                        </Link>
                        <span className="ml-2">{c.title}</span>
                        {c.is_demo && (
                          <span className="ml-2">
                            <DemoBadge />
                          </span>
                        )}
                      </td>
                      <td className="py-2.5 pr-3 text-xs">{WORKFLOW_SHORT[c.workflow]}</td>
                      <td className="py-2.5 pr-3">
                        <Pill label={label} tone={tone} />
                        {c.open_review_tasks > 0 && (
                          <span className="ml-2 text-xs text-amber-800">
                            {c.open_review_tasks} open task{c.open_review_tasks > 1 ? "s" : ""}
                          </span>
                        )}
                      </td>
                      <td className="py-2.5 pr-3 text-xs">{c.entity.code}</td>
                      <td className="py-2.5 text-xs text-muted-foreground">{formatDateTime(c.updated_at)}</td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
        )}
      </Card>
    </AppPage>
  )
}

/** Old address /pod/<slug>/cases: the shared list, filtered to that workflow. */
export function LegacyWorkflowCases() {
  const { slug } = useParams()
  const [params] = useSearchParams()
  const next = new URLSearchParams(params)
  if (workflowFromSlug(slug)) next.set("workflow", slug!)
  return <Navigate to={`/pod/cases?${next.toString()}`} replace />
}
