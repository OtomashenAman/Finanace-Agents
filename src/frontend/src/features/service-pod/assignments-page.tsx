import { useState } from "react"

import { AppPage } from "@/components/layout/app-page"
import { Button } from "@/components/ui/button"
import { AdminTabs } from "@/features/admin/components/admin-tabs"

import type { Capacity, PodUserAccess, Workflow, WorkflowKey } from "./api"
import { Card, LoadError, Loading } from "./components/bits"
import { attempt } from "./ui"
import { usePodAssignments, useSetPodAssignments, useWorkflows } from "./hooks"

const key = (w: WorkflowKey, c: Capacity) => `${w}:${c}`

function UserRow({ user, workflows }: { user: PodUserAccess; workflows: Workflow[] }) {
  const initial = new Set(user.assignments.map((a) => key(a.workflow, a.capacity)))
  const [chosen, setChosen] = useState(initial)
  const save = useSetPodAssignments()
  const dirty = chosen.size !== initial.size || [...chosen].some((k) => !initial.has(k))
  return (
    <tr className="align-top">
      <td className="py-3 pr-4">
        <p className="font-semibold text-brand-navy">{user.full_name}</p>
        <p className="text-xs text-muted-foreground">{user.email}</p>
      </td>
      {workflows.map((w) => (
        <td key={w.key} className="py-3 pr-4">
          {(Object.entries(w.labels) as [Capacity, string][]).map(([capacity, label]) => (
            <label key={capacity} className="flex items-center gap-1.5 text-xs whitespace-nowrap">
              <input
                type="checkbox"
                checked={chosen.has(key(w.key, capacity))}
                onChange={(e) => {
                  const next = new Set(chosen)
                  if (e.target.checked) next.add(key(w.key, capacity))
                  else next.delete(key(w.key, capacity))
                  setChosen(next)
                }}
              />
              {label}
            </label>
          ))}
        </td>
      ))}
      <td className="py-3">
        <Button
          size="sm"
          variant={dirty ? "default" : "outline"}
          disabled={!dirty || save.isPending}
          onClick={() =>
            void attempt(
              () =>
                save.mutateAsync({
                  userId: user.user_id,
                  assignments: [...chosen].map((k) => {
                    const [workflow, capacity] = k.split(":") as [WorkflowKey, Capacity]
                    return { workflow, capacity }
                  }),
                }),
              `Saved ${user.full_name}'s Service POD roles.`,
            )
          }
        >
          Save
        </Button>
      </td>
    </tr>
  )
}

/** Who does what in each Service POD workflow. Changes apply on the user's next request. */
export function PodAssignmentsPage() {
  const users = usePodAssignments()
  const workflows = useWorkflows()
  return (
    <AppPage
      title="Admin Settings"
      subtitle="Service POD roles. Reviewers never act on cases they prepared; the CFO must be a different person from the reviewer."
    >
      <AdminTabs />
      <Card title="Service POD roles" hint="Legal entity access comes from the Users tab, as for the agents.">
        {(users.isPending || workflows.isPending) && <Loading what="roles" />}
        {(users.isError || workflows.isError) && <LoadError what="roles" />}
        {users.data && workflows.data && (
          <div className="overflow-x-auto">
            <table className="w-full min-w-[900px] text-sm">
              <thead>
                <tr className="border-b text-left text-xs tracking-wide text-muted-foreground uppercase">
                  <th className="py-2 pr-4 font-semibold">User</th>
                  {workflows.data.map((w) => (
                    <th key={w.key} className="py-2 pr-4 font-semibold">
                      {w.name}
                    </th>
                  ))}
                  <th />
                </tr>
              </thead>
              <tbody className="divide-y">
                {users.data.map((u) => (
                  <UserRow key={`${u.user_id}:${u.assignments.map((a) => key(a.workflow, a.capacity)).join()}`} user={u} workflows={workflows.data} />
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>
    </AppPage>
  )
}
