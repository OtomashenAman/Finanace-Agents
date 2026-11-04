import { useState } from "react"
import { toast } from "sonner"

import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { errorMessage } from "@/lib/api"

import type { PostingTask } from "../api"
import { useSnapshots, useTaskAction } from "../hooks"
import { formatDateTime } from "../labels"
import { selectClass } from "../ui"
import { GuardedButton } from "./bits"

/** The moves on a manual posting: record the QuickBooks transaction ID once it is posted,
 *  then verify it against a fresh export. Why verification refused stays on screen, not
 *  only in a toast. */
export function TaskActions({ t }: { t: PostingTask }) {
  const act = useTaskAction()
  const { data: snapshots = [] } = useSnapshots()
  const [txn, setTxn] = useState("")
  const [snapshotId, setSnapshotId] = useState("")
  const [refused, setRefused] = useState<string | null>(null)
  const a = t.allowed_actions
  const run = async (action: "record" | "verify" | "cancel", extra = {}) => {
    try {
      const r = await act.mutateAsync({ id: t.id, version: t.version, action, ...extra })
      setRefused(null)
      toast.success(`Task ${r.status.replace("_", " ")}.`)
    } catch (error) {
      const message = errorMessage(error, "That didn't work.")
      setRefused(message)
      toast.error(message)
    }
  }
  return (
    <>
      <div className="mt-2 flex flex-wrap items-center gap-2">
        {t.status === "proposed" && (
          <>
            <Input className="max-w-[220px]" placeholder="QuickBooks transaction ID" value={txn} onChange={(e) => setTxn(e.target.value)} />
            <GuardedButton reason={a.record} disabled={act.isPending || !txn.trim()} onClick={() => void run("record", { external_txn_id: txn })}>
              I posted it
            </GuardedButton>
          </>
        )}
        {t.status === "recorded_unverified" && (
          <>
            <select className={`${selectClass} max-w-xs`} value={snapshotId} onChange={(e) => setSnapshotId(e.target.value)} aria-label="Fresh snapshot">
              <option value="">Fresh snapshot that shows it…</option>
              {snapshots.map((s) => (
                <option key={s.id} value={s.id}>
                  {s.company_name} · as of {s.as_of} · imported {formatDateTime(s.imported_at)}
                </option>
              ))}
            </select>
            <GuardedButton reason={a.verify} disabled={act.isPending || !snapshotId} onClick={() => void run("verify", { snapshot_id: snapshotId })}>
              Verify
            </GuardedButton>
          </>
        )}
        {t.status === "proposed" && a.cancel === null && (
          <Button size="sm" variant="ghost" disabled={act.isPending} onClick={() => void run("cancel")}>
            Cancel
          </Button>
        )}
      </div>
      {refused && <p className="mt-2 rounded-md bg-red-50 px-3 py-2 text-xs text-red-900">Not done: {refused}</p>}
    </>
  )
}
