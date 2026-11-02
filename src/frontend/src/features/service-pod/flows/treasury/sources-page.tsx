import { useState } from "react"
import { Link, useNavigate } from "react-router"

import { Button } from "@/components/ui/button"

import type { TreasurySources } from "../../api"
import { Card, DemoBadge, Empty, LoadError, Loading, Pill } from "../../components/bits"
import { JourneyStrip } from "../../components/case-steps"
import { snapshotKey, splitLatest } from "../../components/latest"
import { WorkflowWorkspace } from "../../components/workspace"
import { useCreateCase, useTreasurySources } from "../../hooks"
import { CASE_STATUS } from "../../labels"
import { attempt } from "../../ui"
import { amount } from "../fpa-trend/meta"
import { HOME_LABEL } from "./meta"
import { TREASURY_STEPS } from "./steps"

function StartForecast({ source }: { source: TreasurySources["sources"][number] }) {
  const create = useCreateCase()
  const navigate = useNavigate()
  const cur = source.snapshot.currency
  const blocked = source.opening_cash === null
  return (
    <div className="space-y-3">
      <dl className="grid gap-3 text-sm sm:grid-cols-4">
        <div>
          <dt className="text-xs text-muted-foreground">Opening cash</dt>
          <dd className="font-semibold tabular-nums">{source.opening_cash ? amount(source.opening_cash, cur) : "-"}</dd>
        </div>
        <div>
          <dt className="text-xs text-muted-foreground">Policy buffer</dt>
          <dd className="font-semibold tabular-nums">{source.policy_buffer ? amount(source.policy_buffer, cur) : "-"}</dd>
        </div>
        <div>
          <dt className="text-xs text-muted-foreground">Approved outflows</dt>
          <dd className="font-semibold tabular-nums">{amount(source.approved_outflows, cur)}</dd>
        </div>
        <div>
          <dt className="text-xs text-muted-foreground">Approved AR promises</dt>
          <dd className="font-semibold tabular-nums">{source.commitments}</dd>
        </div>
      </dl>
      {source.checks.length > 0 && (
        <ul className="space-y-1 text-xs text-amber-800">
          {source.checks.map((c) => (
            <li key={c}>{c}</li>
          ))}
        </ul>
      )}
      <Button
        disabled={blocked || create.isPending}
        onClick={() =>
          void attempt(
            () =>
              create.mutateAsync({
                workflow: "treasury",
                snapshot_id: source.snapshot.id,
                title: `13 weeks from ${source.snapshot.as_of}`,
                selection: {},
              }),
            (c) => `${c.reference} opened.`,
          ).then((c) => c && void navigate(`/pod/cases/${c.id}`))
        }
      >
        Start 13-week forecast
      </Button>
    </div>
  )
}

export function TreasurySourcesPage() {
  const { data, isPending, isError } = useTreasurySources()
  const [allSnapshots, setAllSnapshots] = useState(false)
  const groups = splitLatest(data?.sources ?? [], (s) => snapshotKey(s.snapshot))
  const hidden = [...groups.older.values()].reduce((n, list) => n + list.length, 0)
  const visible = allSnapshots ? (data?.sources ?? []) : groups.latest
  return (
    <WorkflowWorkspace workflow="treasury" homeLabel={HOME_LABEL}>
      <JourneyStrip workflow="treasury" home={HOME_LABEL} steps={TREASURY_STEPS} />
      {isPending && <Loading what="the cash sources" />}
      {isError && <LoadError what="the cash sources" />}
      {data && data.sources.length === 0 && (
        <Card title="No cash source yet">
          <Empty>
            A forecast needs a cleared, reconciled cash position, the approved outflows and the invoices. Import them on{" "}
            <Link to="/pod/sources" className="text-primary hover:underline">
              Sources
            </Link>
            .
          </Empty>
        </Card>
      )}
      <div className="space-y-6">
        {visible.map((src) => (
          <Card
            key={src.snapshot.id}
            title={`${src.snapshot.company_name} · ${src.snapshot.entity.code}`}
            hint={`Cash as of ${src.snapshot.as_of} · ${src.snapshot.currency}`}
            actions={src.snapshot.is_demo ? <DemoBadge /> : undefined}
          >
            <StartForecast source={src} />
          </Card>
        ))}
        {hidden > 0 && (
          <button type="button" className="text-xs text-primary hover:underline" onClick={() => setAllSnapshots(!allSnapshots)}>
            {allSnapshots ? "Show only the latest snapshot of each company" : `Show ${hidden} older snapshot${hidden > 1 ? "s" : ""}`}
          </button>
        )}
        {data && data.cases.length > 0 && (
          <Card title="Forecasts">
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
