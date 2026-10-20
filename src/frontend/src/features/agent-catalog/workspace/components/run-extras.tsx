import { CircleCheck, Download, Landmark, LoaderCircle, TriangleAlert } from "lucide-react"
import { toast } from "sonner"

import { Button } from "@/components/ui/button"
import { errorMessage } from "@/lib/api"

import type { RunDetail } from "../api"
import { formatDateTime } from "../format"
import { useEvidencePack, useWriteBack } from "../hooks"

/** One ZIP with the run, documents' text, source snapshot and audit trail (with hashes). */
export function EvidencePackButton({ agentKey, run }: { agentKey: string; run: RunDetail }) {
  const pack = useEvidencePack(agentKey, run.id)
  return (
    <Button
      type="button"
      variant="outline"
      size="sm"
      onClick={() =>
        pack.mutate(undefined, {
          onError: (error) => toast.error(errorMessage(error, "Couldn't build the evidence pack")),
        })
      }
      disabled={pack.isPending}
    >
      {pack.isPending ? <LoaderCircle className="animate-spin" aria-hidden /> : <Download aria-hidden />}
      Evidence pack
    </Button>
  )
}

/** After approval: note it on the QuickBooks bill the run came from, and show the receipt. */
export function WriteBackPanel({ agentKey, run }: { agentKey: string; run: RunDetail }) {
  const writeBack = useWriteBack(agentKey, run.id)
  const action = run.actions.find((a) => a.kind === "quickbooks.bill_approval_note")
  if (!action && !run.permissions.can_write_back) return null

  return (
    <div className="space-y-2 rounded-md border bg-background p-3">
      <h3 className="flex items-center gap-2 text-sm font-semibold text-brand-navy">
        <Landmark className="size-4" aria-hidden />
        QuickBooks
      </h3>
      {action?.status === "succeeded" && (
        <p className="flex items-start gap-2 text-sm">
          <CircleCheck className="mt-0.5 size-4 shrink-0 text-emerald-600" aria-hidden />
          <span>
            {action.label} (bill {String(action.receipt?.bill_id ?? "")}
            {action.receipt?.already_present ? ", note was already there" : ""}) ·{" "}
            {formatDateTime(action.completed_at)}
          </span>
        </p>
      )}
      {action?.status === "queued" && (
        <p className="flex items-center gap-2 text-sm text-muted-foreground" role="status">
          <LoaderCircle className="size-4 animate-spin" aria-hidden /> Writing to QuickBooks…
        </p>
      )}
      {action?.status === "failed" && (
        <p className="flex items-start gap-2 text-sm text-red-800">
          <TriangleAlert className="mt-0.5 size-4 shrink-0" aria-hidden />
          Write-back failed: {action.error}
        </p>
      )}
      {run.permissions.can_write_back && (
        <>
          <p className="text-xs text-muted-foreground">
            Adds an approval note to the bill in your QuickBooks. Amounts and coding are not changed.
          </p>
          <Button
            type="button"
            size="sm"
            onClick={() =>
              writeBack.mutate(undefined, {
                onError: (error) => toast.error(errorMessage(error, "Couldn't write back to QuickBooks")),
              })
            }
            disabled={writeBack.isPending}
          >
            {writeBack.isPending && <LoaderCircle className="animate-spin" aria-hidden />}
            {action?.status === "failed" ? "Try again" : "Note approval in QuickBooks"}
          </Button>
        </>
      )}
    </div>
  )
}
