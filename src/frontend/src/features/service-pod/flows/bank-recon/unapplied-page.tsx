import { useState } from "react"
import { Link, useNavigate } from "react-router"

import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"

import type { BankWorklist, Snapshot } from "../../api"
import { Card, Empty, LoadError, Loading, Pill } from "../../components/bits"
import { WorkflowWorkspace } from "../../components/workspace"
import { useBankWorklist, useCreateCase, useSnapshotRows } from "../../hooks"
import { CASE_STATUS } from "../../labels"
import { attempt, selectClass } from "../../ui"
import { fmt, useCanPrepare } from "../shared"
import { Kpi, SourceLine } from "../shared-ui"
import { HOME_LABEL } from "./meta"

function OpenReceipt({ row, snapshot }: { row: BankWorklist["rows"][number]; snapshot: Snapshot }) {
  const create = useCreateCase()
  const navigate = useNavigate()
  const customers = useSnapshotRows(row.matched_customer_id ? null : snapshot.id, "customers")
  const [customerId, setCustomerId] = useState(row.matched_customer_id ?? "")
  const [confirmation, setConfirmation] = useState("")
  return (
    <div className="flex flex-wrap items-center gap-2">
      {!row.matched_customer_id && (
        <>
          <select className={`${selectClass} w-auto`} value={customerId} onChange={(e) => setCustomerId(e.target.value)} aria-label="Customer">
            <option value="">Which customer paid…</option>
            {customers.data?.rows.map((c) => (
              <option key={String(c.id)} value={String(c.id)}>
                {String(c.name)}
              </option>
            ))}
          </select>
          <Input className="h-10 max-w-xs" placeholder="How you verified the payer" value={confirmation} onChange={(e) => setConfirmation(e.target.value)} />
        </>
      )}
      <Button
        size="sm"
        disabled={create.isPending || !customerId || !row.cleared}
        title={row.cleared ? undefined : "Only cleared receipts can be applied"}
        onClick={() =>
          void attempt(
            () =>
              create.mutateAsync({
                workflow: "bank_recon",
                snapshot_id: snapshot.id,
                title: `${row.reference} · ${row.payer}`,
                selection: {
                  receipt_reference: row.reference,
                  customer_id: customerId,
                  ...(confirmation.trim() && { payer_confirmation: confirmation }),
                },
              }),
            (c) => `${c.reference} opened.`,
          ).then((c) => c && void navigate(`/pod/cases/${c.id}`))
        }
      >
        Open case
      </Button>
    </div>
  )
}

/** Bank-to-Invoice: cleared receipts not yet recorded in QuickBooks. */
export function UnappliedCashPage() {
  const { data, isPending, isError } = useBankWorklist()
  const canOpen = useCanPrepare("bank_recon")
  return (
    <WorkflowWorkspace workflow="bank_recon" homeLabel={HOME_LABEL}>
      {isPending && <Loading what="receipts" />}
      {isError && <LoadError what="receipts (you need a role in Bank-to-Invoice)" />}
      {data && !data.snapshot && <Empty>No snapshot with bank receipts yet. Add a bank statement on Sources.</Empty>}
      {data?.snapshot && (
        <>
          <SourceLine snapshot={data.snapshot} />
          <div className="grid gap-3 sm:grid-cols-4">
            <Kpi label="Unmatched (cleared)" value={fmt(data.unmatched_total, data.snapshot.currency)} />
            <Kpi label="Receipts" value={data.receipts} />
            <Kpi label="Possible duplicates" value={data.possible_duplicates} />
            <Kpi label="Pending admin" value={data.pending_admin} />
          </div>
          <Card title="Unapplied receipts" className="mt-6">
            {data.rows.length === 0 && <Empty>Every receipt is recorded.</Empty>}
            <ul className="divide-y">
              {data.rows.map((row) => (
                <li key={row.reference} className="space-y-2 py-3 text-sm">
                  <p className="flex flex-wrap items-center gap-2">
                    <span className="font-semibold text-brand-navy">{row.reference}</span>
                    <span>{fmt(row.amount, row.currency)}</span>
                    <span className="text-xs text-muted-foreground">
                      {row.payer} · {row.date}
                    </span>
                    {!row.cleared && <Pill label="Not cleared" tone="warn" />}
                    {row.possible_duplicate && <Pill label="Possible duplicate" tone="bad" />}
                    {row.matched_customer ? <Pill label={`Payer: ${row.matched_customer}`} tone="good" /> : <Pill label="Payer not matched" tone="neutral" />}
                  </p>
                  {row.open_invoices.length > 0 && (
                    <p className="text-xs text-muted-foreground">
                      Open: {row.open_invoices.map((i) => `${i.number} ${fmt(i.balance)}`).join(" · ")} · awaiting the customer's allocation
                    </p>
                  )}
                  {row.open_case ? (
                    <Button asChild size="sm" variant="outline">
                      <Link to={`/pod/cases/${row.open_case.id}`}>
                        {row.open_case.reference} · {CASE_STATUS[row.open_case.status][0]}
                      </Link>
                    </Button>
                  ) : (
                    canOpen && <OpenReceipt row={row} snapshot={data.snapshot!} />
                  )}
                </li>
              ))}
            </ul>
          </Card>
        </>
      )}
    </WorkflowWorkspace>
  )
}
