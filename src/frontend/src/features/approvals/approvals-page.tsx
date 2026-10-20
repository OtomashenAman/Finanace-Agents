import { useState } from "react"
import { Link } from "react-router"
import { Inbox, LoaderCircle } from "lucide-react"

import { AppPage } from "@/components/layout/app-page"
import { Alert } from "@/components/ui/alert"
import { StatusBadge } from "@/features/agent-catalog/workspace/components/status-badge"
import { formatDateTime } from "@/features/agent-catalog/workspace/format"
import { useCurrentUser } from "@/features/auth/hooks"
import { isAdmin } from "@/features/auth/roles"
import { cn } from "@/lib/utils"

import type { ApprovalItem } from "./api"
import { useApprovals } from "./hooks"

function ApprovalsTable({ runs, decided, admin }: { runs: ApprovalItem[]; decided: boolean; admin: boolean }) {
  return (
    <div className="overflow-x-auto">
      <table className="w-full min-w-[720px] text-sm">
        <thead>
          <tr className="border-b text-left text-xs tracking-wide text-muted-foreground uppercase">
            <th className="py-2 pr-4 font-semibold">Run</th>
            <th className="py-2 pr-4 font-semibold">Agent</th>
            <th className="py-2 pr-4 font-semibold">Reference</th>
            <th className="py-2 pr-4 font-semibold">Result</th>
            {admin && <th className="py-2 pr-4 font-semibold">Preparer</th>}
            <th className="py-2 pr-4 font-semibold">{decided ? "Decided" : "Submitted"}</th>
            <th className="py-2 font-semibold">Status</th>
          </tr>
        </thead>
        <tbody className="divide-y">
          {runs.map((run) => (
            <tr key={run.id} className="hover:bg-secondary/40">
              <td className="py-3 pr-4">
                <Link
                  to={`/catalog/${run.agent_key}/runs/${run.id}`}
                  className="font-semibold text-primary hover:underline"
                >
                  {run.reference}
                </Link>
              </td>
              <td className="py-3 pr-4">{run.agent_name}</td>
              <td className="py-3 pr-4">{run.business_reference ?? "—"}</td>
              <td className="py-3 pr-4">
                {run.headline ?? "—"}
                {run.priority === "high" && <span className="ml-2 text-xs font-semibold text-red-700">High priority</span>}
              </td>
              {admin && <td className="py-3 pr-4">{run.preparer.full_name}</td>}
              <td className="py-3 pr-4 whitespace-nowrap text-muted-foreground">
                {formatDateTime(decided ? run.decided_at ?? run.updated_at : run.submitted_at)}
              </td>
              <td className="py-3">
                <StatusBadge status={run.status} label={run.status_label} />
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

/** Finance Admin: everyone's runs waiting for approval. User: the runs they submitted. */
export function ApprovalsPage() {
  const { data: user } = useCurrentUser()
  const admin = isAdmin(user)
  const [showDecided, setDecided] = useState(false)
  // Users only see what's still waiting; the decision history is the admin's
  const decided = admin && showDecided
  const { data: runs, isPending, isError } = useApprovals(decided)
  const tabs = [
    { decided: false, label: "Waiting for approval" },
    { decided: true, label: "Decided" },
  ]

  return (
    <AppPage
      title="Approvals"
      subtitle={
        admin
          ? "Runs submitted by users across all agents. Open one to review the evidence and record a decision."
          : "Your submitted runs waiting for the Finance Admin's approval."
      }
    >
      <section className="rounded-lg border bg-card p-5 sm:p-6">
        {admin && (
          <nav aria-label="Approvals" className="mb-4 flex gap-1 border-b">
            {tabs.map((tab) => (
              <button
                key={tab.label}
                type="button"
                onClick={() => setDecided(tab.decided)}
                aria-pressed={decided === tab.decided}
                className={cn(
                  "-mb-px border-b-2 px-4 py-2.5 text-sm font-medium transition-colors",
                  decided === tab.decided
                    ? "border-primary text-primary"
                    : "border-transparent text-muted-foreground hover:text-foreground",
                )}
              >
                {tab.label}
              </button>
            ))}
          </nav>
        )}

        {isPending && (
          <div className="flex justify-center py-12" role="status">
            <LoaderCircle className="size-6 animate-spin text-primary" aria-hidden />
            <span className="sr-only">Loading approvals…</span>
          </div>
        )}
        {isError && <Alert>Couldn't load approvals. Refresh the page to try again.</Alert>}
        {runs?.length === 0 && (
          <div className="flex flex-col items-center gap-2 py-12 text-center">
            <Inbox className="size-7 text-muted-foreground" aria-hidden />
            <p className="font-medium">{decided ? "No decisions yet" : "Nothing waiting for approval"}</p>
          </div>
        )}
        {runs && runs.length > 0 && <ApprovalsTable runs={runs} decided={decided} admin={admin} />}
      </section>
    </AppPage>
  )
}
