import { useReportMonths } from "../../hooks"
import { StatList } from "../shared-stats"
import { monthLabel } from "../fpa-trend/meta"

export function ReportingStats() {
  const { data, isPending } = useReportMonths()
  if (data && data.sources.length === 0) return <p className="text-xs text-muted-foreground">No source with Balance Sheets and close status yet.</p>
  const suggested = data?.sources.find((s) => s.suggested)?.suggested
  const open = data?.cases.filter((c) => c.status === "draft" || c.status === "approved").length
  const done = data?.cases.filter((c) => c.status === "completed").length
  return (
    <StatList
      loading={isPending}
      items={[
        ["Ready to report", suggested ? monthLabel(suggested) : "-"],
        ["Open packs", open ?? "-"],
        ["Completed", done ?? "-"],
      ]}
    />
  )
}
