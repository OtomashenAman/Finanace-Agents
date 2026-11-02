import { LoaderCircle, RefreshCw } from "lucide-react"
import { toast } from "sonner"

import { Button } from "@/components/ui/button"
import { Card } from "@/features/service-pod/components/bits"
import { errorMessage } from "@/lib/api"

import { useRefreshSanctions, useSanctions } from "../hooks"

/** Finance Admin: the OFAC SDN list vendors are screened against (refreshed daily). */
export function SanctionsCard() {
  const status = useSanctions(true)
  const refresh = useRefreshSanctions()
  const s = status.data
  return (
    <Card
      title="Sanctions list"
      hint="Vendor onboarding screens names against it; with no list loaded, screening refuses to pass anyone."
      actions={
        <Button size="sm" variant="outline" disabled={refresh.isPending}
          onClick={() => refresh.mutate(undefined, {
            onSuccess: (r) => toast.success(`${r.list_name}: ${r.entries.toLocaleString()} entries loaded`),
            onError: (e) => toast.error(errorMessage(e, "Couldn't load the list")),
          })}>
          {refresh.isPending ? <LoaderCircle className="size-4 animate-spin" aria-hidden /> : <RefreshCw className="size-4" aria-hidden />}
          Load now
        </Button>
      }
    >
      {s && (s.loaded ? (
        <p className="text-sm">
          {s.list_name}: {s.entries.toLocaleString()} entries, loaded {s.loaded_at ? new Date(s.loaded_at).toLocaleString() : ""}
        </p>
      ) : (
        <p className="text-sm text-amber-700">Not loaded yet: vendor screening will wait for it.</p>
      ))}
    </Card>
  )
}
