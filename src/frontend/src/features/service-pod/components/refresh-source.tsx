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
  const [id, setId] = useState("")
  if (!newer.length || c.allowed_actions.refresh_source !== null) return null
  return (
    <div className="flex flex-wrap items-center gap-2 rounded-md border border-amber-300 bg-amber-50 p-3 text-sm">
      <RefreshCw className="size-4 text-amber-800" aria-hidden />
      <span>A newer source of these books exists.</span>
      <select className={`${selectClass} w-auto`} value={id} onChange={(e) => setId(e.target.value)} aria-label="Newer snapshot">
        <option value="">Choose…</option>
        {newer.map((s) => (
          <option key={s.id} value={s.id}>
            as of {s.as_of} · imported {formatDateTime(s.imported_at)}
          </option>
        ))}
      </select>
      <Button size="sm" variant="outline" disabled={pending || !id} onClick={() => void run("refresh_source", { snapshot_id: id }, "Case moved to the newer source.")}>
        Use it
      </Button>
    </div>
  )
}
