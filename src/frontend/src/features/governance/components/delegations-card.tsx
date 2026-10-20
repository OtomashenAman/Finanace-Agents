import { useState, type FormEvent } from "react"
import { LoaderCircle } from "lucide-react"
import { toast } from "sonner"

import { Alert } from "@/components/ui/alert"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Panel } from "@/features/agent-catalog/workspace/components/panel"
import { formatDateTime } from "@/features/agent-catalog/workspace/format"
import { useCurrentUser } from "@/features/auth/hooks"
import { errorMessage } from "@/lib/api"
import { cn } from "@/lib/utils"

import { useCancelDelegation, useCreateDelegation, useDelegations } from "../hooks"

const FIELD =
  "flex h-10 w-full rounded-md border border-input bg-background px-3 text-sm focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/20 focus-visible:outline-none"

function localInput(date: Date): string {
  const pad = (n: number) => String(n).padStart(2, "0")
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}T${pad(date.getHours())}:${pad(date.getMinutes())}`
}

/** Let another Finance Admin approve in someone's place for a period (e.g. leave). */
export function DelegationsCard({ admins }: { admins: { id: string; full_name: string }[] }) {
  const { data: me } = useCurrentUser()
  const delegations = useDelegations()
  const create = useCreateDelegation()
  const cancel = useCancelDelegation()
  const [delegator, setDelegator] = useState(me?.id ?? "")
  const [delegate, setDelegate] = useState("")
  const [starts, setStarts] = useState(() => localInput(new Date()))
  const [ends, setEnds] = useState(() => localInput(new Date(Date.now() + 7 * 86_400_000)))
  const [reason, setReason] = useState("")

  const onSubmit = (e: FormEvent) => {
    e.preventDefault()
    if (!delegate) return
    create.mutate(
      {
        delegator_id: delegator || undefined,
        delegate_id: delegate,
        starts_at: new Date(starts).toISOString(),
        ends_at: new Date(ends).toISOString(),
        reason: reason.trim() || undefined,
      },
      {
        onSuccess: () => {
          toast.success("Delegation set up")
          setReason("")
          setDelegate("")
        },
      },
    )
  }

  return (
    <Panel title="Delegated approvers">
      <div className="space-y-5">
        <p className="text-sm text-muted-foreground">
          While active, the delegate may approve wherever the approval matrix names the delegator. Each approval records
          whom it was on behalf of.
        </p>
        <form onSubmit={onSubmit} className="space-y-3" aria-label="New delegation">
          {create.error && <Alert>{errorMessage(create.error, "Couldn't set up the delegation.")}</Alert>}
          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
            <div className="space-y-1.5">
              <Label htmlFor="dlg-from">Approvals of</Label>
              <select id="dlg-from" className={FIELD} value={delegator} onChange={(e) => setDelegator(e.target.value)}>
                {admins.map((a) => (
                  <option key={a.id} value={a.id}>
                    {a.full_name}
                    {a.id === me?.id ? " (you)" : ""}
                  </option>
                ))}
              </select>
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="dlg-to">Delegate to</Label>
              <select id="dlg-to" className={FIELD} value={delegate} onChange={(e) => setDelegate(e.target.value)} required>
                <option value="">Choose…</option>
                {admins
                  .filter((a) => a.id !== delegator)
                  .map((a) => (
                    <option key={a.id} value={a.id}>
                      {a.full_name}
                    </option>
                  ))}
              </select>
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="dlg-start">From</Label>
              <Input id="dlg-start" type="datetime-local" className="h-10 text-sm" value={starts} onChange={(e) => setStarts(e.target.value)} />
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="dlg-end">Until</Label>
              <Input id="dlg-end" type="datetime-local" className="h-10 text-sm" value={ends} onChange={(e) => setEnds(e.target.value)} />
            </div>
          </div>
          <div className="flex flex-wrap items-end gap-3">
            <div className="min-w-0 flex-1 space-y-1.5">
              <Label htmlFor="dlg-reason">Reason (optional)</Label>
              <Input
                id="dlg-reason"
                className="h-10 text-sm"
                value={reason}
                onChange={(e) => setReason(e.target.value)}
                maxLength={300}
                placeholder="e.g. Annual leave"
              />
            </div>
            <Button type="submit" disabled={create.isPending || !delegate || admins.length < 2}>
              {create.isPending && <LoaderCircle className="animate-spin" aria-hidden />}
              Delegate
            </Button>
          </div>
          {admins.length < 2 && <p className="text-xs text-muted-foreground">Delegation needs at least two Finance Admins.</p>}
        </form>

        {delegations.data && delegations.data.length > 0 && (
          <ul className="divide-y rounded-md border">
            {delegations.data.map((d) => (
              <li key={d.id} className="flex flex-wrap items-center justify-between gap-3 px-3 py-2.5 text-sm">
                <div>
                  <p>
                    <span className="font-medium">{d.delegate.full_name}</span> approves for{" "}
                    <span className="font-medium">{d.delegator.full_name}</span>
                    <span
                      className={cn(
                        "ml-2 rounded px-1.5 py-0.5 text-xs font-medium",
                        d.active ? "bg-emerald-50 text-emerald-800" : "bg-muted text-muted-foreground",
                      )}
                    >
                      {d.active ? "Active" : d.cancelled_at ? "Cancelled" : new Date(d.starts_at) > new Date() ? "Scheduled" : "Ended"}
                    </span>
                  </p>
                  <p className="text-xs text-muted-foreground">
                    {formatDateTime(d.starts_at)} → {formatDateTime(d.ends_at)}
                    {d.reason && ` · ${d.reason}`}
                  </p>
                </div>
                {!d.cancelled_at && new Date(d.ends_at) > new Date() && (
                  <Button
                    type="button"
                    size="sm"
                    variant="ghost"
                    disabled={cancel.isPending}
                    onClick={() =>
                      cancel.mutate(d.id, {
                        onSuccess: () => toast.success("Delegation cancelled"),
                        onError: (error) => toast.error(errorMessage(error, "Couldn't cancel")),
                      })
                    }
                  >
                    Cancel
                  </Button>
                )}
              </li>
            ))}
          </ul>
        )}
      </div>
    </Panel>
  )
}
