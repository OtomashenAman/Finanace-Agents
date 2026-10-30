import type { ReactNode } from "react"
import { CircleCheck, CircleDashed, CircleMinus, CircleX } from "lucide-react"

import type { Snapshot } from "../api"
import { DemoBadge } from "../components/bits"
import { money, type InvoiceState } from "./shared"

export function InvoiceTable({ rows, currency }: { rows: InvoiceState[]; currency: unknown }) {
  return (
    <table className="w-full text-sm">
      <thead>
        <tr className="border-b text-left text-xs text-muted-foreground uppercase">
          <th className="py-1.5 pr-3 font-semibold">Invoice</th>
          <th className="py-1.5 pr-3 font-semibold">Due</th>
          <th className="py-1.5 pr-3 text-right font-semibold">Open</th>
          {rows.some((r) => r.days_overdue !== undefined) && <th className="py-1.5 text-right font-semibold">Overdue</th>}
        </tr>
      </thead>
      <tbody className="divide-y">
        {rows.map((r) => (
          <tr key={r.id}>
            <td className="py-1.5 pr-3 font-medium">{r.number}</td>
            <td className="py-1.5 pr-3">{r.due_date}</td>
            <td className="py-1.5 pr-3 text-right tabular-nums">{money(r.balance, currency)}</td>
            {r.days_overdue !== undefined && <td className="py-1.5 text-right">{r.days_overdue} d</td>}
          </tr>
        ))}
      </tbody>
    </table>
  )
}

export function Kpi({ label, value }: { label: string; value: string | number }) {
  return (
    <div className="rounded-lg border bg-card p-4">
      <p className="text-xs tracking-wide text-muted-foreground uppercase">{label}</p>
      <p className="mt-1 text-2xl font-bold text-brand-navy tabular-nums">{value}</p>
    </div>
  )
}

export function SourceLine({ snapshot }: { snapshot: Snapshot | null }) {
  if (!snapshot) return null
  return (
    <p className="mb-4 flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
      Source: {snapshot.company_name} · {snapshot.entity.code} · as of {snapshot.as_of} · {snapshot.basis}
      {snapshot.is_demo && <DemoBadge />}
    </p>
  )
}

export type Check = "done" | "waiting" | "na" | "failed"
const ICON: Record<Check, ReactNode> = {
  done: <CircleCheck className="size-4 text-emerald-700" aria-label="done" />,
  waiting: <CircleDashed className="size-4 text-amber-700" aria-label="waiting" />,
  na: <CircleMinus className="size-4 text-muted-foreground" aria-label="not applicable" />,
  failed: <CircleX className="size-4 text-red-700" aria-label="failed" />,
}

/** One line of a checklist: state icon, what, detail. */
export function CheckRow({ state, label, children }: { state: Check; label: string; children: ReactNode }) {
  return (
    <li className="grid grid-cols-[20px_120px_1fr] items-start gap-2 py-1.5">
      {ICON[state]}
      <span className="font-medium">{label}</span>
      <span className="text-muted-foreground">{children}</span>
    </li>
  )
}
