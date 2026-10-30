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
