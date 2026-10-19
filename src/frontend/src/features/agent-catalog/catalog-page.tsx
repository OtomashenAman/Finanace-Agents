import { Inbox, LoaderCircle } from "lucide-react"

import { AppPage } from "@/components/layout/app-page"
import { Alert } from "@/components/ui/alert"
import { useCurrentUser } from "@/features/auth/hooks"

import { AgentCard } from "./components/agent-card"
import { useAgents } from "./hooks"

export function CatalogPage() {
  const { data: user } = useCurrentUser()
  const { data: agents, isPending, isError } = useAgents()
  const isAdmin = user?.role === "finance_admin"

  return (
    <AppPage
      title="Agent Catalog"
      subtitle="Select an agent to launch its workspace. Access is restricted by role and legal entity."
    >
      {isPending && (
        <div className="flex justify-center py-16" role="status">
          <LoaderCircle className="size-6 animate-spin text-primary" aria-hidden />
          <span className="sr-only">Loading agents…</span>
        </div>
      )}

      {isError && <Alert>Couldn't load the agent catalog. Refresh the page to try again.</Alert>}

      {agents && agents.length === 0 && (
        <div className="flex flex-col items-center gap-2 rounded-lg border border-dashed bg-card px-6 py-16 text-center">
          <Inbox className="size-8 text-muted-foreground" aria-hidden />
          <p className="font-semibold">No agents assigned to you yet</p>
          <p className="text-sm text-muted-foreground">Ask your Finance Admin for access to an agent workspace.</p>
        </div>
      )}

      {agents && agents.length > 0 && (
        <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
          {agents.map((agent) => (
            <AgentCard key={agent.key} agent={agent} canManage={isAdmin} />
          ))}
        </div>
      )}
    </AppPage>
  )
}
