import { useMemo, useState } from "react"
import { Link, useSearchParams } from "react-router"
import { Bot, CircleAlert, Search } from "lucide-react"

import { Input } from "@/components/ui/input"
import { Card, Empty, LoadError, Loading } from "@/features/service-pod/components/bits"
import type { CaseSummary } from "@/features/service-pod/api"
import { selectClass } from "@/features/service-pod/ui"
import { cn } from "@/lib/utils"

import { useFinanceCases, useFinanceDashboard, useFinanceWorkflows } from "./hooks"
import { CASE_STATUS, capacityLabel } from "./labels"
import { FinancePage } from "./components/finance-page"

type View = "mine" | "open" | "released" | "completed" | "cancelled" | "all"

const VIEWS: { key: View; label: string; hint: string }[] = [
  { key: "mine", label: "Needs me", hint: "Cases with something you can do now" },
  { key: "open", label: "In progress", hint: "Steps still to do" },
  { key: "released", label: "Released", hint: "Approved; finishing in the ERP" },
  { key: "completed", label: "Completed", hint: "Done" },
  { key: "cancelled", label: "Cancelled", hint: "Stopped, with the reason" },
  { key: "all", label: "All", hint: "Every case you may see" },
]

function ago(iso: string): string {
  const mins = Math.max(0, Math.round((Date.now() - new Date(iso).getTime()) / 60_000))
  if (mins < 60) return `${mins} min ago`
  const hours = Math.round(mins / 60)
  if (hours < 24) return `${hours} h ago`
  return new Date(iso).toLocaleDateString()
}

/** What happens next on a case, in words, with who does it. */
function Next({ c }: { c: CaseSummary }) {
  if (!c.next_title) return <span className="text-muted-foreground">—</span>
  const agent = c.next_who === "agent"
  return (
    <span className="flex min-w-0 flex-col">
      <span className={cn("truncate", c.next_failed && "text-red-700")}>
        {c.next_failed && <CircleAlert className="mr-1 inline size-3.5" aria-label="The agent couldn't finish" />}
        {c.next_title}
      </span>
      {c.next_who && (
        <span className="text-xs text-muted-foreground">
          {agent ? (
            <><Bot className="mr-0.5 inline size-3" aria-hidden />{c.next_failed ? "agent: run again once fixed" : "agent"}</>
          ) : (
            capacityLabel(c.next_who)
          )}
        </span>
      )}
    </span>
  )
}

export function FinanceCasesPage() {
  const [params, setParams] = useSearchParams()
  const workflow = params.get("workflow")
  const view = (params.get("view") as View | null) ?? "open"
  const [query, setQuery] = useState("")
  const workflows = useFinanceWorkflows()
  const dashboard = useFinanceDashboard()
  const { data, isLoading, isError } = useFinanceCases({ workflow, status: null })
  const nameOf = (key: string) => workflows.data?.find((w) => w.key === key)?.name ?? key
  const set = (key: string, value: string | null) => {
    const next = new URLSearchParams(params)
    if (value) next.set(key, value)
    else next.delete(key)
    setParams(next, { replace: true })
  }

  const mineIds = useMemo(() => new Set((dashboard.data?.my_queue ?? []).map((q) => q.case_id)), [dashboard.data])
  const inView = (c: CaseSummary, v: View) =>
    v === "all" ? true
      : v === "mine" ? mineIds.has(c.id)
        : v === "open" ? c.status === "draft"
          : v === "released" ? c.status === "approved"
            : c.status === v
  const counts = Object.fromEntries(VIEWS.map((v) => [v.key, (data ?? []).filter((c) => inView(c, v.key)).length])) as Record<View, number>
  const needle = query.trim().toLowerCase()
  const shown = (data ?? [])
    .filter((c) => inView(c, view))
    .filter((c) => !needle || `${c.reference} ${c.title}`.toLowerCase().includes(needle))
  const ap = (workflows.data ?? []).filter((w) => w.key.startsWith("ap_"))
  const ar = (workflows.data ?? []).filter((w) => w.key.startsWith("ar_"))

  return (
    <FinancePage title="Finance POD cases" subtitle="Every case you may see: the ones you opened, and those of workflows you take part in.">
      <Card title="Cases">
        <div className="mb-3 flex flex-wrap items-center gap-2">
          <div role="tablist" aria-label="Show" className="flex flex-wrap gap-1.5">
            {VIEWS.map((v) => (
              <button
                key={v.key}
                role="tab"
                aria-selected={view === v.key}
                title={v.hint}
                onClick={() => set("view", v.key === "open" ? null : v.key)}
                className={cn(
                  "rounded-full border px-3 py-1 text-xs font-medium transition-colors",
                  view === v.key ? "border-primary bg-primary text-primary-foreground" : "border-border bg-card text-muted-foreground hover:text-foreground",
                )}
              >
                {v.label} <span className="tabular-nums opacity-80">{counts[v.key]}</span>
              </button>
            ))}
          </div>
          <div className="ml-auto flex w-full flex-wrap gap-2 sm:w-auto">
            <label className="relative w-full sm:w-56">
              <Search className="pointer-events-none absolute left-2.5 top-2.5 size-4 text-muted-foreground" aria-hidden />
              <Input aria-label="Search cases" placeholder="Search reference or title" value={query} onChange={(e) => setQuery(e.target.value)} className="h-9 pl-8" />
            </label>
            <select aria-label="Workflow" className={cn(selectClass, "h-9 w-full sm:w-52")} value={workflow ?? ""} onChange={(e) => set("workflow", e.target.value || null)}>
              <option value="">All workflows</option>
              {ap.length > 0 && (
                <optgroup label="Accounts Payable">
                  {ap.map((w) => <option key={w.key} value={w.key}>{w.name}</option>)}
                </optgroup>
              )}
              {ar.length > 0 && (
                <optgroup label="Accounts Receivable">
                  {ar.map((w) => <option key={w.key} value={w.key}>{w.name}</option>)}
                </optgroup>
              )}
            </select>
          </div>
        </div>
        {isLoading && <Loading what="cases" />}
        {isError && <LoadError what="cases" />}
        {data && shown.length === 0 && (
          <Empty>{view === "mine" ? "Nothing waits on you." : needle ? "No case matches the search." : "No cases here."}</Empty>
        )}
        {shown.length > 0 && (
          <div className="overflow-x-auto">
            <table className="w-full min-w-[720px] text-sm">
              <thead className="text-left text-xs text-muted-foreground">
                <tr>
                  <th className="py-2 pr-3 font-medium">Case</th>
                  <th className="py-2 pr-3 font-medium">Workflow</th>
                  <th className="py-2 pr-3 font-medium">Next</th>
                  <th className="py-2 pr-3 font-medium">Status</th>
                  <th className="py-2 font-medium">Updated</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-border/70">
                {shown.map((c) => (
                  <tr key={c.id} className="align-top hover:bg-muted/40">
                    <td className="max-w-[22rem] py-2.5 pr-3">
                      <Link to={`/finance/cases/${c.id}`} className="font-medium text-primary hover:underline">
                        {c.reference}
                      </Link>
                      <span className="block truncate text-muted-foreground">{c.title}</span>
                      {c.open_review_tasks > 0 && (
                        <span className="mt-0.5 inline-block rounded bg-rose-50 px-1.5 text-[11px] font-medium text-rose-800">
                          {c.open_review_tasks} review task{c.open_review_tasks === 1 ? "" : "s"}
                        </span>
                      )}
                    </td>
                    <td className="py-2.5 pr-3">
                      <span className="mr-1.5 rounded bg-muted px-1 font-mono text-[10px] text-muted-foreground">
                        {c.workflow.startsWith("ar_") ? "AR" : "AP"}
                      </span>
                      {nameOf(c.workflow)}
                    </td>
                    <td className="max-w-[16rem] py-2.5 pr-3"><Next c={c} /></td>
                    <td className="py-2.5 pr-3">
                      <span className={cn("whitespace-nowrap rounded-full px-2 py-0.5 text-xs font-medium", CASE_STATUS[c.status].className)}>
                        {c.status === "approved" ? "Released" : CASE_STATUS[c.status].label}
                      </span>
                    </td>
                    <td className="whitespace-nowrap py-2.5 text-xs text-muted-foreground" title={new Date(c.updated_at).toLocaleString()}>
                      {ago(c.updated_at)}
                    </td>
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
