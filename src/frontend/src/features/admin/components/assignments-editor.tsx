import { LoaderCircle } from "lucide-react"

import { Alert } from "@/components/ui/alert"
import type { AgentCapacity } from "@/features/agent-catalog/api"
import { useAgents } from "@/features/agent-catalog/hooks"

import type { Assignment } from "../api"

const CAPACITIES: { capacity: AgentCapacity; label: string; hint: string }[] = [
  { capacity: "preparer", label: "Prepare", hint: "start runs and see results" },
  { capacity: "reviewer", label: "Approve", hint: "review other users' runs" },
]

interface AssignmentsEditorProps {
  value: Assignment[]
  onChange: (value: Assignment[]) => void
  disabled?: boolean
}

/** Agent × capacity checkboxes. The admin's own catalog lists every agent. */
export function AssignmentsEditor({ value, onChange, disabled }: AssignmentsEditorProps) {
  const { data: agents, isPending, isError } = useAgents()

  const has = (agentKey: string, capacity: AgentCapacity) =>
    value.some((a) => a.agent_key === agentKey && a.capacity === capacity)

  const toggle = (agentKey: string, capacity: AgentCapacity, checked: boolean) =>
    onChange(
      checked
        ? [...value, { agent_key: agentKey, capacity }]
        : value.filter((a) => !(a.agent_key === agentKey && a.capacity === capacity)),
    )

  if (isPending) {
    return (
      <div className="flex justify-center py-6" role="status">
        <LoaderCircle className="size-5 animate-spin text-primary" aria-hidden />
        <span className="sr-only">Loading agents…</span>
      </div>
    )
  }
  if (isError) return <Alert>Couldn't load the agents.</Alert>

  return (
    <div className="overflow-x-auto">
      <table className="w-full min-w-[420px] text-sm">
        <thead>
          <tr className="border-b text-left text-xs tracking-wide text-muted-foreground uppercase">
            <th className="py-2 pr-4 font-semibold">Agent</th>
            {CAPACITIES.map(({ capacity, label, hint }) => (
              <th key={capacity} className="w-24 py-2 text-center font-semibold" title={hint}>
                {label}
              </th>
            ))}
          </tr>
        </thead>
        <tbody className="divide-y">
          {agents.map((agent) => (
            <tr key={agent.key}>
              <td className="py-2.5 pr-4">
                <span className="font-medium">{agent.short_name}</span>
                {!agent.is_active && <span className="ml-2 text-xs text-muted-foreground">(disabled)</span>}
              </td>
              {CAPACITIES.map(({ capacity, label }) => (
                <td key={capacity} className="py-2.5 text-center">
                  <input
                    type="checkbox"
                    className="size-4 accent-primary"
                    checked={has(agent.key, capacity)}
                    onChange={(e) => toggle(agent.key, capacity, e.target.checked)}
                    disabled={disabled}
                    aria-label={`${label}: ${agent.short_name}`}
                  />
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
      <p className="mt-3 text-xs text-muted-foreground">
        Prepare: start runs and see results. Approve: review runs prepared by someone else.
      </p>
    </div>
  )
}
