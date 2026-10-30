import { useState } from "react"
import { Link, useNavigate } from "react-router"
import { Plus } from "lucide-react"

import { AppPage } from "@/components/layout/app-page"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"

import type { CaseStatus, Workflow, WorkflowKey } from "./api"
import { Card, DemoBadge, Empty, Field, LoadError, Loading, Pill, PodTabs } from "./components/bits"
import { attempt, selectClass } from "./ui"
import { useCases, useCreateCase, useSnapshots, useWorkflows } from "./hooks"
import { CASE_STATUS, COLLECTION_LABEL, formatDateTime, WORKFLOW_SHORT } from "./labels"

function NewCase({ workflows, onDone }: { workflows: Workflow[]; onDone: () => void }) {
  const mine = workflows.filter((w) => w.my_capacities.includes("preparer"))
  const [workflow, setWorkflow] = useState<WorkflowKey | "">(mine[0]?.key ?? "")
  const [snapshotId, setSnapshotId] = useState("")
  const [title, setTitle] = useState("")
  const { data: snapshots = [] } = useSnapshots()
  const create = useCreateCase()
  const navigate = useNavigate()
  const spec = mine.find((w) => w.key === workflow)
  const usable = snapshots.filter((s) => spec?.required.every((c) => s.coverage.includes(c)))

  return (
    <form
      className="grid gap-3 sm:grid-cols-2"
      onSubmit={(e) => {
        e.preventDefault()
        if (!workflow) return
        void attempt(
          () => create.mutateAsync({ workflow, snapshot_id: snapshotId, title }),
          (c) => `${c.reference} opened.`,
        ).then((c) => {
          if (c) {
            onDone()
            void navigate(`/pod/cases/${c.id}`)
          }
        })
      }}
    >
      <Field label="Workflow">
        <select className={selectClass} value={workflow} onChange={(e) => setWorkflow(e.target.value as WorkflowKey)}>
          {mine.map((w) => (
            <option key={w.key} value={w.key}>
              {w.name}
            </option>
          ))}
        </select>
      </Field>
      <Field
        label="Source snapshot"
        hint={spec ? `Needs: ${spec.required.map((c) => COLLECTION_LABEL[c]).join(", ")}` : undefined}
      >
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
      <Field label="Title" hint="e.g. the customer, the period or the bank reference">
        <Input value={title} maxLength={200} onChange={(e) => setTitle(e.target.value)} />
      </Field>
      <div className="flex items-end">
        <Button type="submit" size="sm" disabled={!workflow || !snapshotId || !title.trim() || create.isPending}>
          Open case
        </Button>
      </div>
    </form>
  )
}

/** Every case the viewer prepares or reviews, across the five workflows. */
export function CasesPage() {
  const workflows = useWorkflows()
  const [workflow, setWorkflow] = useState<string>("")
  const [status, setStatus] = useState<string>("")
  const [creating, setCreating] = useState(false)
  const cases = useCases({ workflow: workflow || null, status: status || null })
  const canCreate = workflows.data?.some((w) => w.my_capacities.includes("preparer"))

  return (
    <AppPage
      title="Service POD"
      subtitle="Five governed finance workflows on read-only QuickBooks data. Finance Admin posts manually."
    >
      <PodTabs />
      <div className="space-y-6">
        {workflows.data && (
          <ul className="grid gap-3 sm:grid-cols-2 xl:grid-cols-5">
            {workflows.data.map((w) => (
              <li key={w.key} className="rounded-lg border bg-card p-4">
                <p className="font-semibold text-brand-navy">{w.name}</p>
                <p className="mt-1 text-xs text-muted-foreground">{w.description}</p>
                <p className="mt-2 text-xs">
                  {w.my_capacities.length
                    ? `You: ${w.my_capacities.map((c) => w.labels[c] ?? c).join(", ")}`
                    : "No role assigned"}
                </p>
              </li>
            ))}
          </ul>
        )}

        <Card
          title="Cases"
          actions={
            canCreate && (
              <Button size="sm" variant={creating ? "outline" : "default"} onClick={() => setCreating((v) => !v)}>
                <Plus /> {creating ? "Close" : "New case"}
              </Button>
            )
          }
        >
          {creating && workflows.data && (
            <div className="mb-4 rounded-md bg-secondary/40 p-4">
              <NewCase workflows={workflows.data} onDone={() => setCreating(false)} />
            </div>
          )}
          <div className="mb-3 flex flex-wrap gap-2">
            <select className={`${selectClass} w-auto`} value={workflow} onChange={(e) => setWorkflow(e.target.value)} aria-label="Workflow">
              <option value="">All workflows</option>
              {Object.entries(WORKFLOW_SHORT).map(([k, v]) => (
                <option key={k} value={k}>
                  {v}
                </option>
              ))}
            </select>
            <select className={`${selectClass} w-auto`} value={status} onChange={(e) => setStatus(e.target.value)} aria-label="Status">
              <option value="">Any status</option>
              {Object.entries(CASE_STATUS).map(([k, [label]]) => (
                <option key={k} value={k}>
                  {label}
                </option>
              ))}
            </select>
          </div>
          {cases.isPending && <Loading what="cases" />}
          {cases.isError && <LoadError what="cases" />}
          {cases.data?.length === 0 && <Empty>No cases yet.</Empty>}
          {!!cases.data?.length && (
            <div className="overflow-x-auto">
              <table className="w-full min-w-[640px] text-sm">
                <thead>
                  <tr className="border-b text-left text-xs tracking-wide text-muted-foreground uppercase">
                    <th className="py-2 pr-3 font-semibold">Case</th>
                    <th className="py-2 pr-3 font-semibold">Workflow</th>
                    <th className="py-2 pr-3 font-semibold">Entity</th>
                    <th className="py-2 pr-3 font-semibold">Owner</th>
                    <th className="py-2 pr-3 font-semibold">Status</th>
                    <th className="py-2 font-semibold">Updated</th>
                  </tr>
                </thead>
                <tbody className="divide-y">
                  {cases.data.map((c) => {
                    const [label, tone] = CASE_STATUS[c.status as CaseStatus]
                    return (
                      <tr key={c.id} className="hover:bg-secondary/40">
                        <td className="py-2.5 pr-3">
                          <Link to={`/pod/cases/${c.id}`} className="font-semibold text-primary hover:underline">
                            {c.reference}
                          </Link>
                          <span className="ml-2">{c.title}</span>
                          {c.is_demo && <span className="ml-2"><DemoBadge /></span>}
                        </td>
                        <td className="py-2.5 pr-3">{WORKFLOW_SHORT[c.workflow]}</td>
                        <td className="py-2.5 pr-3">{c.entity.code}</td>
                        <td className="py-2.5 pr-3">{c.owner.name}</td>
                        <td className="py-2.5 pr-3">
                          <Pill label={label} tone={tone} />
                          {c.open_review_tasks > 0 && (
                            <span className="ml-2 text-xs text-amber-800">{c.open_review_tasks} open</span>
                          )}
                        </td>
                        <td className="py-2.5 text-xs text-muted-foreground">{formatDateTime(c.updated_at)}</td>
                      </tr>
                    )
                  })}
                </tbody>
              </table>
            </div>
          )}
        </Card>
      </div>
    </AppPage>
  )
}
