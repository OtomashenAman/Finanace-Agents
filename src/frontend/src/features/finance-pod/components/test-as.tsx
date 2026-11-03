import { useState } from "react"
import { useQuery } from "@tanstack/react-query"
import { ExternalLink, FlaskConical } from "lucide-react"
import { Link } from "react-router"
import { toast } from "sonner"

import { useActAs, useCurrentUser } from "@/features/auth/hooks"
import { errorMessage } from "@/lib/api"

import { financeApi } from "../api"
import { capacityLabel } from "../labels"

/** A Finance Admin testing the workflow: the people who hold this step's capacity, each with
 *  a button opening a new tab signed in as them (this tab stays the admin's). Someone kept
 *  out by segregation of duties is shown with the reason. Dev and demo only. */
export function TestAs({ caseId, step, capacity }: { caseId: string; step?: string; capacity: string }) {
  const { data: me } = useCurrentUser()
  const [open, setOpen] = useState(false)
  const people = useQuery({
    queryKey: ["finance", "step-people", caseId, step ?? capacity],
    queryFn: () => financeApi.stepPeople(caseId, step ? { step } : { capacity }),
    enabled: Boolean(me?.can_act_as) && open,
  })
  const actAs = useActAs()
  if (!me?.can_act_as) return null
  const role = capacityLabel(capacity).toLowerCase()
  const go = (userId: string) =>
    actAs.mutate(
      { userId, path: window.location.pathname },
      { onError: (e) => toast.error(errorMessage(e, "Couldn't open a tab as them.")) },
    )
  return (
    <div className="mt-2 rounded-lg border border-dashed border-current/30 bg-white/50 p-2.5 text-sm">
      <button type="button" onClick={() => setOpen((v) => !v)} className="flex items-center gap-1.5 font-medium" aria-expanded={open}>
        <FlaskConical className="size-4" aria-hidden /> Testing? Do it as the {role}
      </button>
      {open && (
        <div className="mt-2 space-y-1.5">
          <p className="text-xs opacity-80">Opens a new tab signed in as them, no password needed. This tab stays yours, and the audit trail records it as your test.</p>
          {people.isPending && <p className="text-xs">Loading…</p>}
          {people.isError && <p className="text-xs text-red-700">{errorMessage(people.error, "Couldn't load who holds it.")}</p>}
          {people.data?.length === 0 && (
            <p className="text-xs">
              Nobody holds the {role} capacity for this entity yet. Give it to a user under{" "}
              <Link to="/finance/setup" className="font-medium underline">Setup</Link>, then come back.
            </p>
          )}
          <ul className="space-y-1">
            {people.data?.map((p) => (
              <li key={p.id} className="flex flex-wrap items-center gap-x-2 gap-y-0.5">
                <span className="min-w-0 [overflow-wrap:anywhere]"><strong>{p.full_name}</strong> <span className="text-xs opacity-75">{p.email}</span></span>
                {p.blocked ? (
                  <span className="text-xs text-red-700">{p.blocked}</span>
                ) : (
                  <button type="button" disabled={actAs.isPending} onClick={() => go(p.id)}
                    className="inline-flex items-center gap-1 rounded-md border border-current/30 bg-white px-2 py-0.5 text-xs font-medium hover:bg-secondary">
                    Open as {p.full_name.split(" ")[0]} <ExternalLink className="size-3" aria-hidden />
                  </button>
                )}
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  )
}
