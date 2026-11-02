import { useState } from "react"
import { Link, useNavigate } from "react-router"

import { Button } from "@/components/ui/button"

import type { FpaPeriodSource } from "../../api"
import { Card, DemoBadge, Empty, LoadError, Loading, Pill } from "../../components/bits"
import { JourneyStrip } from "../../components/case-steps"
import { WorkflowWorkspace } from "../../components/workspace"
import { useCreateCase, useFpaPeriods } from "../../hooks"
import { CASE_STATUS } from "../../labels"
import { attempt, selectClass } from "../../ui"
import { HOME_LABEL, monthLabel } from "./meta"
import { FPA_STEPS } from "./steps"

/** Pick consecutive months of one source and start the analysis (deck FP&A step 1). */
function StartAnalysis({ source }: { source: FpaPeriodSource }) {
  const create = useCreateCase()
  const navigate = useNavigate()
  const months = source.months
  const [start, setStart] = useState(source.suggested_start ?? months[0] ?? "")
  const [end, setEnd] = useState(source.suggested_end ?? months.at(-1) ?? "")
  const [unit, setUnit] = useState("")
  const valid = start && end && start < end
  const title = `${monthLabel(start)} – ${monthLabel(end)}${unit ? ` · ${unit}` : ""}`
  return (
    <div className="grid items-end gap-3 sm:grid-cols-[1fr_1fr_1fr_auto]">
      <label className="space-y-1 text-sm">
        <span className="font-medium text-brand-navy">From</span>
        <select className={selectClass} value={start} onChange={(e) => setStart(e.target.value)}>
          {months.map((m) => (
            <option key={m} value={m}>
              {monthLabel(m)}
            </option>
          ))}
        </select>
      </label>
      <label className="space-y-1 text-sm">
        <span className="font-medium text-brand-navy">To</span>
        <select className={selectClass} value={end} onChange={(e) => setEnd(e.target.value)}>
          {months.map((m) => (
            <option key={m} value={m}>
              {monthLabel(m)}
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
        disabled={!valid || create.isPending}
        onClick={() =>
          void attempt(
            () =>
              create.mutateAsync({
                workflow: "fpa_trend",
                snapshot_id: source.snapshot.id,
                title,
                selection: { start, end, ...(unit ? { business_unit: unit } : {}) },
              }),
            (c) => `${c.reference} opened.`,
          ).then((c) => c && void navigate(`/pod/cases/${c.id}`))
        }
      >
        Start {valid ? title : "analysis"}
      </Button>
    </div>
  )
}

export function FpaPeriodsPage() {
  const { data, isPending, isError } = useFpaPeriods()
  return (
    <WorkflowWorkspace workflow="fpa_trend" homeLabel={HOME_LABEL}>
      <JourneyStrip workflow="fpa_trend" home={HOME_LABEL} steps={FPA_STEPS} />
      {isPending && <Loading what="the periods" />}
      {isError && <LoadError what="the periods" />}
      {data && data.sources.length === 0 && (
        <Card title="No P&L source yet">
          <Empty>
            FP&A needs a source with accounts, GL lines and transactions. Import one on{" "}
            <Link to="/pod/sources" className="text-primary hover:underline">
              Sources
            </Link>
            : a QuickBooks Online snapshot reads the P&L by month and its detail.
          </Empty>
        </Card>
      )}
      <div className="space-y-6">
        {data?.sources.map((src) => (
          <Card
            key={src.snapshot.id}
            title={`${src.snapshot.company_name} · ${src.snapshot.entity.code}`}
            hint={`${src.months.length} months with P&L lines (${monthLabel(src.months[0] ?? "")} to ${monthLabel(src.months.at(-1) ?? "")}) · ${src.snapshot.basis} · as of ${src.snapshot.as_of}`}
            actions={src.snapshot.is_demo ? <DemoBadge /> : undefined}
          >
            <StartAnalysis source={src} />
          </Card>
        ))}
        {data && data.cases.length > 0 && (
          <Card title="FP&A cases">
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
