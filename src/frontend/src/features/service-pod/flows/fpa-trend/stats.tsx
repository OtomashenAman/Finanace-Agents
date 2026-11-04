import { useFpaPeriods } from "../../hooks"
import { StatList } from "../shared-stats"
import { monthLabel } from "./meta"

export function FpaStats() {
  const { data, isPending } = useFpaPeriods()
  if (data && data.sources.length === 0) return <p className="text-xs text-muted-foreground">No source with P&L lines yet.</p>
  const latest = data?.sources[0]
  const open = data?.cases.filter((c) => c.status === "draft" || c.status === "approved").length
  return (
    <StatList
      loading={isPending}
      items={[
        ["Latest month", latest?.months.at(-1) ? monthLabel(latest.months.at(-1)!) : "-"],
        ["Months", latest?.months.length ?? "-"],
        ["Open cases", open ?? "-"],
      ]}
    />
  )
}
