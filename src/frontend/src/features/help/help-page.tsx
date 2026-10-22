import type { ReactNode } from "react"
import { Link } from "react-router"

import { AppPage } from "@/components/layout/app-page"
import { Panel } from "@/features/agent-catalog/workspace/components/panel"
import { useCurrentUser } from "@/features/auth/hooks"
import { isAdmin } from "@/features/auth/roles"

interface Topic {
  title: string
  steps: ReactNode[]
}

const EVERYONE: Topic[] = [
  {
    title: "Run an agent",
    steps: [
      <>
        Open the <Link to="/catalog" className="text-primary hover:underline">Agent Catalog</Link> and pick an agent
        assigned to you.
      </>,
      "Enter the figures, upload the document or pick a record from a connected data source.",
      "Choose Analyze: the agent checks the numbers, raises flags and writes a short narrative.",
      "Fix anything flagged, then Submit for approval. You can follow it on the run page.",
    ],
  },
  {
    title: "Connect your data",
    steps: [
      <>
        On <Link to="/data-sources" className="text-primary hover:underline">Data Sources</Link>, connect QuickBooks
        with your own Intuit app's Client ID and Secret, or upload a CSV/Excel file.
      </>,
      "Your connections and uploads are private to you. Sync to pull the latest bills and invoices.",
      "If a connection asks to reconnect, sign in to QuickBooks again from the same card.",
    ],
  },
  {
    title: "Know what needs you",
    steps: [
      <>
        <Link to="/worklist" className="text-primary hover:underline">My Worklist</Link> lists what you should do next,
        most urgent first, and what is waiting on others.
      </>,
      "When an approver asks for changes, the run comes back with their comment. Update it and submit again.",
      <>
        <Link to="/audit" className="text-primary hover:underline">Audit Trail</Link> shows everything you did and
        everything that happened on your runs.
      </>,
    ],
  },
  {
    title: "Your account",
    steps: [
      <>
        Change your password on <Link to="/account" className="text-primary hover:underline">My account</Link> (the key
        icon at the top right). Your other sessions are signed out.
      </>,
      "Forgot it? Choose “Forgot password?” on the sign-in page: a Finance Admin is asked to set a new one.",
      "The person icon lets you sign in with another account in this tab; other tabs keep their own session.",
    ],
  },
]

const ADMIN: Topic[] = [
  {
    title: "Approve runs",
    steps: [
      <>
        <Link to="/approvals" className="text-primary hover:underline">Approvals</Link> lists submitted runs. Open one,
        check the result, flags and source data, then approve, request changes or reject.
      </>,
      "Large amounts may need more than one approver (Governance → Approval matrix).",
      "After approval, download the evidence pack or write the result back to QuickBooks from the run page.",
    ],
  },
  {
    title: "Manage people and access",
    steps: [
      <>
        <Link to="/admin/users" className="text-primary hover:underline">Users</Link>: add people, set their role,
        assign agents and legal entities, unlock accounts and set new passwords.
      </>,
      "Password reset requests from the sign-in page appear in your worklist.",
      "Delegations let someone approve on your behalf while you are away.",
    ],
  },
  {
    title: "Governance and monitoring",
    steps: [
      "Governance: self-approval, review SLA, per-agent thresholds (each change is versioned) and the approval matrix.",
      "AI monitoring: model calls, failures, cost and the background job queue, with retry for failed jobs.",
      "The audit trail is tamper-checked and kept for the configured retention period.",
    ],
  },
]

export function HelpPage() {
  const { data: user } = useCurrentUser()
  const topics = isAdmin(user) ? [...EVERYONE, ...ADMIN] : EVERYONE
  return (
    <AppPage title="Help" subtitle="How to get things done in the Finance Agent Command Center. Press Ctrl K (⌘ K) to search.">
      <div className="grid items-start gap-6 lg:grid-cols-2">
        {topics.map((t) => (
          <Panel key={t.title} title={t.title}>
            <ol className="list-decimal space-y-2 pl-5 text-sm">
              {t.steps.map((s, i) => (
                <li key={i}>{s}</li>
              ))}
            </ol>
          </Panel>
        ))}
      </div>
    </AppPage>
  )
}
