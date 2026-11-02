import { useTreasurySources } from "../../hooks"
import { StatList } from "../shared-stats"
import { amount } from "../fpa-trend/meta"

export function TreasuryStats() {
  const { data, isPending } = useTreasurySources()
  if (data && data.sources.length === 0) return <p className="text-xs text-muted-foreground">No source with a cash position yet.</p>
  const src = data?.sources[0]
  const cur = src?.snapshot.currency ?? ""
  return (
    <StatList
      loading={isPending}
      items={[
        ["Opening cash", src?.opening_cash ? amount(src.opening_cash, cur) : "-"],
        ["Buffer", src?.policy_buffer ? amount(src.policy_buffer, cur) : "-"],
        ["Promises", src?.commitments ?? "-"],
      ]}
    />
  )
}
