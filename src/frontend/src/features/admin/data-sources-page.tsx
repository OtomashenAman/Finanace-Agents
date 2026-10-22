import { LoaderCircle } from "lucide-react"

import { AppPage } from "@/components/layout/app-page"
import { Alert } from "@/components/ui/alert"
import { Panel } from "@/features/agent-catalog/workspace/components/panel"
import { formatDateTime } from "@/features/agent-catalog/workspace/format"
import { StatusPill } from "@/features/data-sources/components/source-card"
import { useAllSources } from "@/features/data-sources/hooks"

import { AdminTabs } from "./components/admin-tabs"

function AllSources() {
  const { data: sources, isPending, isError } = useAllSources()
  return (
    <Panel title="Users' data sources">
      <p className="mb-4 text-sm text-muted-foreground">
        Status only: each user's records and credentials stay private to them.
      </p>
      {isPending && <LoaderCircle className="size-5 animate-spin text-primary" aria-label="Loading" />}
      {isError && <Alert>Couldn't load data sources.</Alert>}
      {sources?.length === 0 && <p className="text-sm text-muted-foreground">No user has connected or uploaded data yet.</p>}
      {sources && sources.length > 0 && (
        <div className="overflow-x-auto">
          <table className="w-full min-w-[560px] text-sm">
            <thead>
              <tr className="border-b text-left text-xs tracking-wide text-muted-foreground uppercase">
                <th className="py-2 pr-4 font-semibold">User</th>
                <th className="py-2 pr-4 font-semibold">Source</th>
                <th className="py-2 pr-4 font-semibold">Last synced</th>
                <th className="py-2 font-semibold">Status</th>
              </tr>
            </thead>
            <tbody className="divide-y">
              {sources.map((s) => (
                <tr key={s.id}>
                  <td className="py-3 pr-4">
                    <p className="font-medium">{s.owner.full_name}</p>
                    <p className="text-xs text-muted-foreground">{s.owner.email}</p>
                  </td>
                  <td className="py-3 pr-4">
                    {s.name}
                    <p className="text-xs text-muted-foreground">{s.kind === "quickbooks" ? "QuickBooks" : "Upload"}</p>
                  </td>
                  <td className="py-3 pr-4">{formatDateTime(s.last_synced_at)}</td>
                  <td className="py-3">
                    <StatusPill source={s} />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </Panel>
  )
}

/** Status of every user's connections. Each user brings their own QuickBooks app and data. */
export function AdminDataSourcesPage() {
  return (
    <AppPage
      title="Admin Settings · Data sources"
      subtitle="Each user connects their own QuickBooks app and company or uploads their own files."
    >
      <AdminTabs />
      <AllSources />
    </AppPage>
  )
}
