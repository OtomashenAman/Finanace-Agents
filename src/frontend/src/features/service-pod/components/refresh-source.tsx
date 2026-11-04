import { useState } from "react"
import { RefreshCw } from "lucide-react"

import { Button } from "@/components/ui/button"

import type { CaseDetail } from "../api"
import { useSnapshots } from "../hooks"
import { formatDateTime } from "../labels"
import { selectClass } from "../ui"
import { useRunAction } from "../use-run-action"

/** Move the case to a newer snapshot of the same books (approvals then need redoing). */
export function RefreshSource({ c }: { c: CaseDetail }) {
  const { run, pending } = useRunAction(c)
  const { data: snapshots = [] } = useSnapshots()
  const newer = snapshots.filter(
    (s) => s.company_id === c.snapshot.company_id && s.entity.id === c.entity.id && s.imported_at > c.snapshot.imported_at,
  )
  const latest = [...newer].sort((a, b) => (a.imported_at < b.imported_at ? 1 : -1))[0]
  const [id, setId] = useState("")
  const [choosing, setChoosing] = useState(false)
  if (!newer.length || c.allowed_actions.refresh_source !== null) return null
  const target = id || latest!.id
  return (
    <div className="flex flex-wrap items-center gap-2 rounded-lg border border-amber-200 bg-amber-50/70 px-3 py-1.5 text-xs text-amber-900">
      <RefreshCw className="size-3.5" aria-hidden />
      <span>
        Newer books available (as of {latest!.as_of}). Moving the case recalculates it; sign-offs are given again.
      </span>
      {choosing && newer.length > 1 && (
        <select className={`${selectClass} h-7 w-auto text-xs`} value={target} onChange={(e) => setId(e.target.value)} aria-label="Newer snapshot">
          {newer.map((s) => (
            <option key={s.id} value={s.id}>
              as of {s.as_of} · imported {formatDateTime(s.imported_at)}
            </option>
          ))}
        </select>
      )}
      <span className="ml-auto flex items-center gap-1">
        {newer.length > 1 && !choosing && (
          <button type="button" className="px-1 hover:underline" onClick={() => setChoosing(true)}>
            Choose another
          </button>
        )}
        <Button size="sm" variant="outline" className="h-7 text-xs" disabled={pending} onClick={() => void run("refresh_source", { snapshot_id: target }, "Case moved to the newer source.")}>
          Update case
        </Button>
      </span>
    </div>
  )
}
