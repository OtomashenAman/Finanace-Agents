import { Link } from "react-router"
import { toast } from "sonner"

import { Switch } from "@/components/ui/switch"
import { ApiError } from "@/lib/api"
import { cn } from "@/lib/utils"

import type { Agent } from "../api"
import { useSetAgentActive } from "../hooks"

interface AgentCardProps {
  agent: Agent
  canManage: boolean
}

export function AgentCard({ agent, canManage }: AgentCardProps) {
  const setActive = useSetAgentActive()

  const toggle = (isActive: boolean) =>
    setActive.mutate(
      { key: agent.key, isActive },
      {
        onSuccess: () => toast.success(`${agent.short_name} ${isActive ? "enabled" : "disabled"}`),
        onError: (error) =>
          toast.error(error instanceof ApiError ? error.message : `Couldn't update ${agent.short_name}`),
      },
    )

  return (
    <article
      className={cn(
        "flex min-h-[116px] flex-col rounded-lg border bg-card p-5 transition-opacity",
        !agent.is_active && "opacity-60",
      )}
      aria-label={agent.name}
    >
      <div className="flex min-w-0 flex-1 flex-col">
        <div className="flex items-start justify-between gap-3">
          <h2 className="text-[15px] leading-snug font-semibold text-brand-navy">{agent.name}</h2>
          {canManage && (
            <Switch
              checked={agent.is_active}
              onCheckedChange={toggle}
              disabled={setActive.isPending}
              aria-label={`${agent.is_active ? "Disable" : "Enable"} ${agent.name}`}
              className="mt-0.5"
            />
          )}
        </div>
        <div className="mt-auto flex items-center gap-3 pt-4">
          {agent.is_active ? (
            <Link
              to={`/catalog/${agent.key}`}
              className="text-sm font-semibold text-primary underline-offset-4 hover:underline"
            >
              Open workspace
            </Link>
          ) : (
            <span className="rounded bg-muted px-2 py-0.5 text-xs font-medium text-muted-foreground">Inactive</span>
          )}
        </div>
      </div>
    </article>
  )
}
