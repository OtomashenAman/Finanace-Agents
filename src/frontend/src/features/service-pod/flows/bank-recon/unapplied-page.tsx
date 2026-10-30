import { Fragment, useState } from "react"
import { Link, useNavigate } from "react-router"

import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"

import type { BankWorklist, Snapshot } from "../../api"
import { Card, Empty, LoadError, Loading, Pill } from "../../components/bits"
import { JourneyStrip } from "../../components/case-steps"
import { WorkflowWorkspace } from "../../components/workspace"
import { useBankWorklist, useCreateCase, useSnapshotRows } from "../../hooks"
import { CASE_STATUS } from "../../labels"
import { attempt, selectClass } from "../../ui"
import { fmt } from "../shared"
import { Kpi, SourceLine, Toolbar } from "../shared-ui"
import { HOME_LABEL } from "./meta"
import { BANK_STEPS } from "./steps"

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

type Row = BankWorklist["rows"][number]
type Filter = "all" | "cleared" | "uncleared" | "nocase"
const PAGE = 10

/** Bank-to-Invoice (deck bank screen 1): receipts not yet recorded in QuickBooks, as a
 *  searchable table; nothing is applied from an amount alone. */
export function UnappliedCashPage() {
  const { data, isPending, isError } = useBankWorklist()
  const [search, setSearch] = useState("")
  const [filter, setFilter] = useState<Filter>("all")
  const [showAll, setShowAll] = useState(false)
  const [opening, setOpening] = useState<string | null>(null)

  const all = data?.rows ?? []
  const tests: Record<Filter, (r: Row) => boolean> = {
    all: () => true,
    cleared: (r) => r.cleared,
    uncleared: (r) => !r.cleared,
    nocase: (r) => r.cleared && r.open_case === null,
  }
  const q = search.trim().toLowerCase()
  const rows = all.filter(
    (r) => tests[filter](r) && (!q || r.reference.toLowerCase().includes(q) || r.payer.toLowerCase().includes(q)),
  )
  const visible = showAll ? rows : rows.slice(0, PAGE)

  return (
    <WorkflowWorkspace workflow="bank_recon" homeLabel={HOME_LABEL}>
      <JourneyStrip workflow="bank_recon" home={HOME_LABEL} steps={BANK_STEPS} />
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
          <Card title="Unapplied receipts" className="mt-6" hint="Cleared bank receipts not yet recorded in QuickBooks; open a case to ask the customer how to apply them.">
            <Toolbar<Filter>
              search={search}
              onSearch={setSearch}
              placeholder="Search reference or payer…"
              active={filter}
              onFilter={setFilter}
              filters={[
                { key: "all", label: "All", count: all.length },
                { key: "cleared", label: "Cleared", count: all.filter(tests.cleared).length },
                { key: "uncleared", label: "Not cleared", count: all.filter(tests.uncleared).length },
                { key: "nocase", label: "Needs a case", count: all.filter(tests.nocase).length },
              ]}
            />
            {rows.length === 0 ? (
              <Empty>No receipt matches.</Empty>
            ) : (
              <div className="overflow-x-auto">
                <table className="w-full min-w-[760px] text-sm">
                  <thead>
                    <tr className="border-b text-left text-xs tracking-wide text-muted-foreground uppercase">
                      <th className="py-2 pr-3 font-semibold">Reference</th>
                      <th className="py-2 pr-3 font-semibold">Payer</th>
                      <th className="py-2 pr-3 font-semibold">Date</th>
                      <th className="py-2 pr-3 text-right font-semibold">Amount</th>
                      <th className="py-2 pr-3 font-semibold">Status</th>
                      <th className="py-2 pr-3 text-right font-semibold">Open inv.</th>
                      <th className="py-2" />
                    </tr>
                  </thead>
                  <tbody className="divide-y">
                    {visible.map((row) => (
                      <Fragment key={row.reference}>
                        <tr className="hover:bg-secondary/30">
                          <td className="py-2 pr-3 font-medium text-brand-navy">{row.reference}</td>
                          <td className="py-2 pr-3">
                            {row.payer}
                            <span className="block text-xs text-muted-foreground">
                              {row.matched_customer ? `= ${row.matched_customer}` : "payer not matched"}
                            </span>
                          </td>
                          <td className="py-2 pr-3 tabular-nums">{row.date}</td>
                          <td className="py-2 pr-3 text-right tabular-nums">{fmt(row.amount, row.currency)}</td>
                          <td className="py-2 pr-3">
                            <span className="flex flex-wrap gap-1">
                              {!row.cleared && <Pill label="Not cleared" tone="warn" />}
                              {row.possible_duplicate && <Pill label="Possible duplicate" tone="bad" />}
                              {row.cleared && !row.possible_duplicate && <Pill label="Cleared" tone="good" />}
                            </span>
                          </td>
                          <td className="py-2 pr-3 text-right tabular-nums" title={row.open_invoices.map((i) => `${i.number} ${fmt(i.balance)}`).join(", ")}>
                            {row.open_invoices.length}
                          </td>
                          <td className="py-2 text-right">
                            {row.open_case ? (
                              <Button asChild size="sm" variant="outline">
                                <Link to={`/pod/cases/${row.open_case.id}`}>
                                  {row.open_case.reference} · {CASE_STATUS[row.open_case.status][0]}
                                </Link>
                              </Button>
                            ) : (
                              row.cleared && (
                                <Button size="sm" variant={opening === row.reference ? "outline" : "default"} onClick={() => setOpening(opening === row.reference ? null : row.reference)}>
                                  {opening === row.reference ? "Close" : "Open case…"}
                                </Button>
                              )
                            )}
                          </td>
                        </tr>
                        {opening === row.reference && (
                          <tr>
                            <td colSpan={7} className="bg-secondary/30 px-3 py-3">
                              <OpenReceipt row={row} snapshot={data.snapshot!} />
                            </td>
                          </tr>
                        )}
                      </Fragment>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
            {rows.length > PAGE && (
              <Button size="sm" variant="ghost" className="mt-2" onClick={() => setShowAll((v) => !v)}>
                {showAll ? "Show fewer" : `Show all ${rows.length}`}
              </Button>
            )}
          </Card>
        </>
      )}
    </WorkflowWorkspace>
  )
}
