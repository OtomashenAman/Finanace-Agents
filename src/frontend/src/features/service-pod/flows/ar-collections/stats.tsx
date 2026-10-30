import { useArPortfolio } from "../../hooks"
import { fmt } from "../shared"
import { StatList } from "../shared-stats"

export function ArStats() {
  const { data, isPending } = useArPortfolio()
  if (data && !data.snapshot) return <p className="text-xs text-muted-foreground">No source data yet.</p>
  return (
    <StatList
      loading={isPending}
      items={[
        ["AR balance", data ? fmt(data.ar_balance, data.currency) : "-"],
        ["Overdue > 30 d", data ? fmt(data.overdue_over_30, data.currency) : "-"],
        ["Exceptions", data?.open_exceptions ?? "-"],
      ]}
    />
  )
}
