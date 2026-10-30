import { useBankWorklist } from "../../hooks"
import { fmt } from "../shared"
import { StatList } from "../shared-stats"

export function BankStats() {
  const { data, isPending } = useBankWorklist()
  if (data && !data.snapshot) return <p className="text-xs text-muted-foreground">No bank receipts yet.</p>
  return (
    <StatList
      loading={isPending}
      items={[
        ["Unmatched", data?.snapshot ? fmt(data.unmatched_total, data.snapshot.currency) : "-"],
        ["Receipts", data?.receipts ?? "-"],
        ["Pending admin", data?.pending_admin ?? "-"],
      ]}
    />
  )
}
