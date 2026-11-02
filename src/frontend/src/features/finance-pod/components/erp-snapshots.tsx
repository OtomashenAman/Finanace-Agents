import { useState } from "react"
import { useMutation, useQuery } from "@tanstack/react-query"
import { Link } from "react-router"
import { Camera, LoaderCircle } from "lucide-react"
import { toast } from "sonner"

import { Button } from "@/components/ui/button"
import { useDataSources } from "@/features/data-sources/hooks"
import { useEntities } from "@/features/entities/hooks"
import { podApi } from "@/features/service-pod/api"
import { Card, DemoBadge, Empty } from "@/features/service-pod/components/bits"
import { COLLECTION_LABEL } from "@/features/service-pod/labels"
import { selectClass } from "@/features/service-pod/ui"
import { errorMessage } from "@/lib/api"
import { cn } from "@/lib/utils"

import { FINANCE_TAG } from "../hooks"

const SNAPSHOTS_KEY = [FINANCE_TAG, "erp-snapshots"] as const

/** Finance Admin: freeze the connected ERPNext company into a read-only snapshot, which the
 *  AP workflows open their cases on. */
export function ErpSnapshots() {
  const sources = useDataSources()
  const entities = useEntities()
  const snapshots = useQuery({
    queryKey: SNAPSHOTS_KEY,
    queryFn: async () => (await podApi.snapshots()).filter((s) => s.source_type === "erpnext"),
  })
  const take = useMutation({ mutationFn: podApi.importErpNext, meta: { invalidates: [FINANCE_TAG, "pod"] } })
  const erpSources = sources.data?.filter((s) => s.kind === "erpnext") ?? []
  const [sourceId, setSourceId] = useState("")
  const [entityId, setEntityId] = useState("")
  const chosenSource = sourceId || erpSources[0]?.id || ""
  const chosenEntity = entityId || entities.data?.find((e) => e.is_active)?.id || ""

  const onTake = () =>
    take.mutate(
      { data_source_id: chosenSource, entity_id: chosenEntity },
      {
        onSuccess: (r) =>
          r.created
            ? toast.success("Snapshot taken", { description: `${r.snapshot.company_name}, as of ${r.snapshot.as_of}` })
            : toast.info("Nothing changed in ERPNext since the last snapshot"),
        onError: (error) => toast.error(errorMessage(error, "Couldn't read ERPNext")),
      },
    )

  return (
    <Card
      title="ERPNext snapshots"
      hint="A read-only copy of the ERPNext company's purchasing data. Cases open on a snapshot, so every figure they use can be traced back."
    >
      {erpSources.length === 0 ? (
        <Empty icon={<Camera className="size-5" />}>
          No ERPNext connection yet. <Link to="/data-sources" className="text-primary underline">Connect ERPNext</Link> under
          Data Sources first.
        </Empty>
      ) : (
        <div className="flex flex-wrap items-end gap-2">
          <label className="space-y-1 text-sm">
            <span className="font-medium">Connection</span>
            <select className={cn(selectClass, "w-56")} value={chosenSource} onChange={(e) => setSourceId(e.target.value)}>
              {erpSources.map((s) => (
                <option key={s.id} value={s.id}>
                  {s.name} · {s.external_id}
                </option>
              ))}
            </select>
          </label>
          <label className="space-y-1 text-sm">
            <span className="font-medium">Legal entity</span>
            <select className={cn(selectClass, "w-48")} value={chosenEntity} onChange={(e) => setEntityId(e.target.value)}>
              {entities.data
                ?.filter((e) => e.is_active)
                .map((e) => (
                  <option key={e.id} value={e.id}>
                    {e.code} · {e.name}
                  </option>
                ))}
            </select>
          </label>
          <Button onClick={onTake} disabled={take.isPending || !chosenSource || !chosenEntity}>
            {take.isPending ? <LoaderCircle className="animate-spin" aria-hidden /> : <Camera aria-hidden />}
            Take snapshot
          </Button>
        </div>
      )}

      {snapshots.data && snapshots.data.length > 0 && (
        <ul className="mt-4 divide-y divide-border/70">
          {snapshots.data.slice(0, 5).map((s) => (
            <li key={s.id} className="py-2 text-sm">
              <div className="flex flex-wrap items-center gap-2">
                <span className="font-medium">{s.company_name}</span>
                <span className="text-muted-foreground">
                  {s.entity.code} · as of {s.as_of} · {new Date(s.imported_at).toLocaleString()}
                </span>
                {s.is_demo && <DemoBadge />}
              </div>
              <p className="mt-0.5 text-xs text-muted-foreground">
                {s.coverage
                  .map((c) => `${(s.row_counts[c] ?? 0).toLocaleString()} ${COLLECTION_LABEL[c].toLowerCase()}`)
                  .join(" · ")}
              </p>
            </li>
          ))}
        </ul>
      )}
    </Card>
  )
}
