import { useState } from "react"
import { Link, useNavigate } from "react-router"

import { Button } from "@/components/ui/button"

import type { ReportMonths } from "../../api"
import { Card, DemoBadge, Empty, LoadError, Loading, Pill } from "../../components/bits"
import { JourneyStrip } from "../../components/case-steps"
import { WorkflowWorkspace } from "../../components/workspace"
import { useCreateCase, useReportMonths } from "../../hooks"
import { CASE_STATUS } from "../../labels"
import { attempt, selectClass } from "../../ui"
import { monthLabel } from "../fpa-trend/meta"
import { HOME_LABEL } from "./meta"
import { REPORTING_STEPS } from "./steps"

function StartPack({ source }: { source: ReportMonths["sources"][number] }) {
  const create = useCreateCase()
  const navigate = useNavigate()
  const usable = source.months.filter((m) => m.prior_available)
  const [month, setMonth] = useState(source.suggested ?? usable[0]?.month ?? "")
  const [unit, setUnit] = useState("")
  const picked = source.months.find((m) => m.month === month)
  const title = `${monthLabel(month)} management pack${unit ? ` · ${unit}` : ""}`
  return (
    <div className="space-y-3">
      <div className="grid items-end gap-3 sm:grid-cols-[1fr_1fr_auto]">
        <label className="space-y-1 text-sm">
          <span className="font-medium text-brand-navy">Report month</span>
          <select className={selectClass} value={month} onChange={(e) => setMonth(e.target.value)}>
            {usable.map((m) => (
              <option key={m.month} value={m.month}>
                {monthLabel(m.month)}
                {m.closed ? "" : " (open)"}
                {m.balance_sheet ? "" : " (no balance sheet)"}
              </option>
            ))}
          </select>
        </label>
        <label className="space-y-1 text-sm">
          <span className="font-medium text-brand-navy">Business unit</span>
          <select className={selectClass} value={unit} onChange={(e) => setUnit(e.target.value)} disabled={source.business_units.length === 0}>
            <option value="">Whole company</option>
            {source.business_units.map((u) => (
              <option key={u} value={u}>
                {u}
              </option>
            ))}
          </select>
        </label>
        <Button
          disabled={!month || create.isPending}
          onClick={() =>
            void attempt(
              () =>
                create.mutateAsync({
                  workflow: "reporting",
                  snapshot_id: source.snapshot.id,
                  title,
                  selection: { month, ...(unit ? { business_unit: unit } : {}) },
                }),
              (c) => `${c.reference} opened.`,
            ).then((c) => c && void navigate(`/pod/cases/${c.id}`))
          }
        >
          Start {month ? `${monthLabel(month)} pack` : "pack"}
        </Button>
      </div>
      {picked && (!picked.closed || !picked.balance_sheet) && (
        <p className="text-xs text-amber-800">
          {!picked.closed && "This month isn't closed in the source. "}
          {!picked.balance_sheet && "The source has no Balance Sheet for it. "}
          The case will open, but the pack can't be signed off until the source has it.
        </p>
      )}
    </div>
  )
}

export function ReportMonthsPage() {
  const { data, isPending, isError } = useReportMonths()
  return (
    <WorkflowWorkspace workflow="reporting" homeLabel={HOME_LABEL}>
      <JourneyStrip workflow="reporting" home={HOME_LABEL} steps={REPORTING_STEPS} />
      {isPending && <Loading what="the report months" />}
      {isError && <LoadError what="the report months" />}
      {data && data.sources.length === 0 && (
        <Card title="No source for a pack yet">
          <Empty>
            A management pack needs P&L lines, transactions, Balance Sheets, the close status and invoices. Import them on{" "}
            <Link to="/pod/sources" className="text-primary hover:underline">
              Sources
            </Link>
            : a QuickBooks Online snapshot reads all of them.
          </Empty>
        </Card>
      )}
      <div className="space-y-6">
        {data?.sources.map((src) => (
          <Card
            key={src.snapshot.id}
            title={`${src.snapshot.company_name} · ${src.snapshot.entity.code}`}
            hint={`${src.months.filter((m) => m.closed).length} closed of ${src.months.length} months · ${src.snapshot.basis} · as of ${src.snapshot.as_of}`}
            actions={src.snapshot.is_demo ? <DemoBadge /> : undefined}
          >
            <StartPack source={src} />
          </Card>
        ))}
        {data && data.cases.length > 0 && (
          <Card title="Management packs">
            <ul className="divide-y">
              {data.cases.map((c) => {
                const [label, tone] = CASE_STATUS[c.status]
                return (
                  <li key={c.id} className="flex items-center gap-3 py-2 text-sm">
                    <Link to={`/pod/cases/${c.id}`} className="font-semibold text-primary hover:underline">
                      {c.reference}
                    </Link>
                    <span className="flex-1">{c.title}</span>
                    <Pill label={label} tone={tone} />
                  </li>
                )
              })}
            </ul>
          </Card>
        )}
      </div>
    </WorkflowWorkspace>
  )
}
