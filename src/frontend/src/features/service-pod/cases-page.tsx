import { useState } from "react"
import { Link, Navigate, useNavigate, useParams, useSearchParams } from "react-router"
import { Plus } from "lucide-react"

import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"

import type { Workflow } from "./api"
import { Card, DemoBadge, Empty, Field, LoadError, Loading, Pill } from "./components/bits"
import { WorkflowWorkspace } from "./components/workspace"
import { FLOW_UI } from "./flows"
import { useCases, useCreateCase, useSnapshots, useWorkflows } from "./hooks"
import { CASE_STATUS, COLLECTION_LABEL, formatDateTime, WORKFLOW_SLUG, workflowFromSlug } from "./labels"
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

/** One workflow's cases. */
export function WorkflowCasesPage() {
  const { slug } = useParams()
  const key = workflowFromSlug(slug)
  const { data: workflows } = useWorkflows()
  const [status, setStatus] = useState("")
  const [creating, setCreating] = useState(false)
  const cases = useCases({ workflow: key ?? null, status: status || null })
  const [params, setParams] = useSearchParams()
  if (!key) return <Navigate to="/pod" replace />
  const steps = FLOW_UI[key]?.steps ?? []
  const stepLabel = (stage: string) => steps.find((s) => s.key === stage)?.label
  // ?stage=email: the open cases waiting on that step (from the journey on the home screen)
  const stage = params.get("stage")
  const rows = stage ? cases.data?.filter((c) => c.stage === stage) : cases.data

  const spec = workflows?.find((w) => w.key === key)
  const home = FLOW_UI[key]?.home
  const canCreate = !home

  return (
    <WorkflowWorkspace workflow={key} homeLabel={home?.label}>
      <Card
        title="Cases"
        hint={home ? <>Open a case from <Link to={`/pod/${WORKFLOW_SLUG[key]}`} className="text-primary hover:underline">{home.label}</Link>, where it starts from the right customer or receipt.</> : undefined}
        actions={
          <div className="flex gap-2">
            <select className={`${selectClass} w-auto`} value={status} onChange={(e) => setStatus(e.target.value)} aria-label="Status">
              <option value="">Any status</option>
              {Object.entries(CASE_STATUS).map(([k, [label]]) => (
                <option key={k} value={k}>
                  {label}
                </option>
              ))}
            </select>
            {canCreate && (
              <Button size="sm" variant={creating ? "outline" : "default"} onClick={() => setCreating((v) => !v)}>
                <Plus /> {creating ? "Close" : "New case"}
              </Button>
            )}
          </div>
        }
      >
        {creating && spec && (
          <div className="mb-4 rounded-md bg-secondary/40 p-4">
            <NewCase spec={spec} onDone={() => setCreating(false)} />
          </div>
        )}
        {stage && stepLabel(stage) && (
          <p className="mb-3 flex items-center gap-2 text-sm">
            Waiting on step: <Pill label={stepLabel(stage)!} tone="info" />
            <button type="button" className="text-xs text-primary hover:underline" onClick={() => setParams({})}>
              show all cases
            </button>
          </p>
        )}
        {cases.isPending && <Loading what="cases" />}
        {cases.isError && <LoadError what="cases" />}
        {rows?.length === 0 && <Empty>{stage ? "No case is on this step now." : "No cases yet."}</Empty>}
        {!!rows?.length && (
          <div className="overflow-x-auto">
            <table className="w-full min-w-[560px] text-sm">
              <thead>
                <tr className="border-b text-left text-xs tracking-wide text-muted-foreground uppercase">
                  <th className="py-2 pr-3 font-semibold">Case</th>
                  <th className="py-2 pr-3 font-semibold">Entity</th>
                  <th className="py-2 pr-3 font-semibold">Opened by</th>
                  <th className="py-2 pr-3 font-semibold">Status</th>
                  {steps.length > 0 && <th className="py-2 pr-3 font-semibold">Step</th>}
                  <th className="py-2 font-semibold">Updated</th>
                </tr>
              </thead>
              <tbody className="divide-y">
                {rows.map((c) => {
                  const [label, tone] = CASE_STATUS[c.status]
                  return (
                    <tr key={c.id} className="hover:bg-secondary/40">
                      <td className="py-2.5 pr-3">
                        <Link to={`/pod/cases/${c.id}${stepLabel(c.stage) ? `?step=${c.stage}` : ""}`} className="font-semibold text-primary hover:underline">
                          {c.reference}
                        </Link>
                        <span className="ml-2">{c.title}</span>
                        {c.is_demo && (
                          <span className="ml-2">
                            <DemoBadge />
                          </span>
                        )}
                      </td>
                      <td className="py-2.5 pr-3">{c.entity.code}</td>
                      <td className="py-2.5 pr-3">{c.owner.name}</td>
                      <td className="py-2.5 pr-3">
                        <Pill label={label} tone={tone} />
                        {c.open_review_tasks > 0 && <span className="ml-2 text-xs text-amber-800">{c.open_review_tasks} open</span>}
                      </td>
                      {steps.length > 0 && <td className="py-2.5 pr-3 text-xs">{stepLabel(c.stage) ?? (c.stage === "done" ? "Closed" : "-")}</td>}
                      <td className="py-2.5 text-xs text-muted-foreground">{formatDateTime(c.updated_at)}</td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
        )}
      </Card>
    </WorkflowWorkspace>
  )
}
