import { useState } from "react"
import { LoaderCircle, Plus, Trash2 } from "lucide-react"
import { toast } from "sonner"

import { Alert } from "@/components/ui/alert"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { parseMoneyInput } from "@/features/agent-catalog/workspace/format"
import { errorMessage } from "@/lib/api"

import type { ApprovalMatrix, ApprovalTierIn } from "../api"
import { useSaveMatrix } from "../hooks"

interface Admin {
  id: string
  full_name: string
}

const SELECT =
  "flex h-9 rounded-md border border-input bg-background px-2 text-sm focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/20 focus-visible:outline-none"

function toEditable(matrix: ApprovalMatrix): ApprovalTierIn[] {
  return matrix.tiers.map((t) => ({
    min_amount: t.min_amount,
    approvals_required: t.approvals_required,
    approver_ids: t.approvers.map((a) => a.id),
  }))
}

/** Amount tiers for one agent: from which amount up, how many approvals, by whom. */
export function ApprovalMatrixCard({ matrix, admins }: { matrix: ApprovalMatrix; admins: Admin[] }) {
  const save = useSaveMatrix()
  const [tiers, setTiers] = useState(() => toEditable(matrix))
  const dirty = JSON.stringify(tiers) !== JSON.stringify(toEditable(matrix))

  const update = (i: number, patch: Partial<ApprovalTierIn>) =>
    setTiers(tiers.map((t, j) => (j === i ? { ...t, ...patch } : t)))

  const toggleApprover = (i: number, id: string, on: boolean) =>
    update(i, {
      approver_ids: on ? [...tiers[i]!.approver_ids, id] : tiers[i]!.approver_ids.filter((a) => a !== id),
    })

  const addTier = () => {
    const highest = Math.max(-1, ...tiers.map((t) => Number(t.min_amount) || 0))
    setTiers([
      ...tiers,
      { min_amount: highest < 0 ? "0" : String(highest + 10000), approvals_required: tiers.length ? 2 : 1, approver_ids: [] },
    ])
  }

  const onSave = () =>
    save.mutate(
      {
        key: matrix.agent_key,
        tiers: tiers.map((t) => ({ ...t, min_amount: parseMoneyInput(t.min_amount) || "0" })),
      },
      {
        onSuccess: (saved) => {
          setTiers(toEditable(saved))
          toast.success("Approval matrix saved", { description: "Runs submitted from now on use it." })
        },
      },
    )

  return (
    <section className="rounded-lg border bg-card p-5 sm:p-6" aria-label={`${matrix.agent_name} approval matrix`}>
      <div className="flex flex-wrap items-start justify-between gap-3 border-b pb-4">
        <div>
          <h3 className="text-base font-semibold text-brand-navy">{matrix.agent_name}</h3>
          <p className="text-xs text-muted-foreground">
            Routed on: {matrix.amount_label ?? "no amount (lowest tier applies)"}
          </p>
        </div>
        <Button type="button" size="sm" variant="outline" onClick={addTier} disabled={tiers.length >= 10}>
          <Plus aria-hidden />
          Add tier
        </Button>
      </div>

      <div className="space-y-4 pt-4">
        {save.error && <Alert>{errorMessage(save.error, "Couldn't save the approval matrix.")}</Alert>}
        {tiers.length === 0 && (
          <p className="text-sm text-muted-foreground">
            No tiers: every run needs one approval from any Finance Admin.
          </p>
        )}
        {tiers.map((t, i) => {
            return (
              <div key={i} className="space-y-3 rounded-md border bg-background p-3">
                <div className="flex flex-wrap items-center gap-2 text-sm">
                  <span>From</span>
                  <Input
                    className="h-9 w-36 text-sm"
                    inputMode="decimal"
                    value={t.min_amount}
                    onChange={(e) => update(i, { min_amount: e.target.value })}
                    aria-label="Tier starts at amount"
                  />
                  <span>and above, needs</span>
                  <select
                    className={SELECT}
                    value={t.approvals_required}
                    onChange={(e) => update(i, { approvals_required: Number(e.target.value) })}
                    aria-label="Approvals required"
                  >
                    {[1, 2, 3].map((n) => (
                      <option key={n} value={n}>
                        {n} approval{n > 1 ? "s" : ""}
                      </option>
                    ))}
                  </select>
                  <button
                    type="button"
                    onClick={() => setTiers(tiers.filter((_, j) => j !== i))}
                    className="ml-auto rounded p-1.5 text-muted-foreground hover:bg-secondary hover:text-foreground"
                    aria-label="Remove tier"
                  >
                    <Trash2 className="size-4" />
                  </button>
                </div>
                <fieldset>
                  <legend className="text-xs text-muted-foreground">
                    Approvers {t.approver_ids.length ? "" : "(none ticked = any Finance Admin)"}
                  </legend>
                  <div className="mt-1.5 flex flex-wrap gap-x-4 gap-y-1.5">
                    {admins.map((a) => (
                      <label key={a.id} className="flex items-center gap-2 text-sm">
                        <input
                          type="checkbox"
                          className="size-4 accent-primary"
                          checked={t.approver_ids.includes(a.id)}
                          onChange={(e) => toggleApprover(i, a.id, e.target.checked)}
                        />
                        {a.full_name}
                      </label>
                    ))}
                  </div>
                </fieldset>
              </div>
            )
          })}
        <div className="flex flex-wrap items-center gap-3">
          <Button type="button" onClick={onSave} disabled={!dirty || save.isPending}>
            {save.isPending && <LoaderCircle className="animate-spin" aria-hidden />}
            Save matrix
          </Button>
          <p className="text-xs text-muted-foreground">
            Below the lowest tier, one approval by any Finance Admin. With 2+ approvals, each must come from a different
            admin. Submitted runs keep the tier they got.
          </p>
        </div>
      </div>
    </section>
  )
}
