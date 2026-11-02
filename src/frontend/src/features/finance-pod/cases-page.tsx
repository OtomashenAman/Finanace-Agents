import { Link, useSearchParams } from "react-router"

import { Card, Empty, LoadError, Loading } from "@/features/service-pod/components/bits"
import { selectClass } from "@/features/service-pod/ui"
import { cn } from "@/lib/utils"

import { useFinanceCases, useFinanceWorkflows } from "./hooks"
import { CASE_STATUS } from "./labels"
import { FinancePage } from "./components/finance-page"

export function FinanceCasesPage() {
  const [params, setParams] = useSearchParams()
  const workflow = params.get("workflow")
  const status = params.get("status")
  const workflows = useFinanceWorkflows()
  const { data, isLoading, isError } = useFinanceCases({ workflow, status })
  const nameOf = (key: string) => workflows.data?.find((w) => w.key === key)?.name ?? key
  const setFilter = (key: string, value: string) => {
    const next = new URLSearchParams(params)
    if (value) next.set(key, value)
    else next.delete(key)
    setParams(next, { replace: true })
  }

  return (
    <FinancePage title="Finance POD cases" subtitle="Every case you may see: the ones you opened, and those of workflows you review.">
      <Card
        title="Cases"
        actions={
          <div className="flex gap-2">
            <select aria-label="Workflow" className={cn(selectClass, "h-9 w-48")} value={workflow ?? ""} onChange={(e) => setFilter("workflow", e.target.value)}>
              <option value="">All workflows</option>
              {workflows.data?.map((w) => (
                <option key={w.key} value={w.key}>
                  {w.name}
                </option>
              ))}
            </select>
            <select aria-label="Status" className={cn(selectClass, "h-9 w-40")} value={status ?? ""} onChange={(e) => setFilter("status", e.target.value)}>
              <option value="">Any status</option>
              {Object.entries(CASE_STATUS).map(([key, meta]) => (
                <option key={key} value={key}>
                  {meta.label}
                </option>
              ))}
            </select>
          </div>
        }
      >
        {isLoading && <Loading what="cases" />}
        {isError && <LoadError what="cases" />}
        {data && data.length === 0 && <Empty>No cases yet.</Empty>}
        {data && data.length > 0 && (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead className="text-left text-xs text-muted-foreground">
                <tr>
                  <th className="py-2 pr-3 font-medium">Case</th>
                  <th className="py-2 pr-3 font-medium">Workflow</th>
                  <th className="py-2 pr-3 font-medium">Entity</th>
                  <th className="py-2 pr-3 font-medium">Step</th>
                  <th className="py-2 pr-3 font-medium">Status</th>
                  <th className="py-2 font-medium">Updated</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-border/70">
                {data.map((c) => (
                  <tr key={c.id}>
                    <td className="py-2 pr-3">
                      <Link to={`/finance/cases/${c.id}`} className="font-medium text-primary hover:underline">
                        {c.reference}
                      </Link>{" "}
                      <span className="text-muted-foreground">{c.title}</span>
                    </td>
                    <td className="py-2 pr-3">{nameOf(c.workflow)}</td>
                    <td className="py-2 pr-3">{c.entity.code}</td>
                    <td className="py-2 pr-3 font-mono text-xs">{c.stage ?? "—"}</td>
                    <td className="py-2 pr-3">
                      <span className={cn("rounded-full px-2 py-0.5 text-xs font-medium", CASE_STATUS[c.status].className)}>
                        {CASE_STATUS[c.status].label}
                      </span>
                    </td>
                    <td className="py-2 text-xs text-muted-foreground">{new Date(c.updated_at).toLocaleString()}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>
    </FinancePage>
  )
}
