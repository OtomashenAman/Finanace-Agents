import type { ReactNode } from "react"
import { Search } from "lucide-react"

import { Input } from "@/components/ui/input"
import { cn } from "@/lib/utils"
import { CircleCheck, CircleDashed, CircleMinus, CircleX } from "lucide-react"

import type { Snapshot } from "../api"
import { DemoBadge } from "../components/bits"
import { fmt, money, type InvoiceState } from "./shared"

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


/** Search box plus filter chips (with counts) above a worklist table. */
export function Toolbar<K extends string>({
  search,
  onSearch,
  placeholder,
  filters,
  active,
  onFilter,
}: {
  search: string
  onSearch: (value: string) => void
  placeholder: string
  filters: { key: K; label: string; count: number }[]
  active: K
  onFilter: (key: K) => void
}) {
  return (
    <div className="mb-3 flex flex-wrap items-center gap-2">
      <div className="relative">
        <Search className="pointer-events-none absolute top-1/2 left-2.5 size-4 -translate-y-1/2 text-muted-foreground" aria-hidden />
        <Input className="h-9 w-56 pl-8 text-sm" placeholder={placeholder} value={search} onChange={(e) => onSearch(e.target.value)} />
      </div>
      <div className="flex flex-wrap gap-1">
        {filters.map((f) => (
          <button
            key={f.key}
            type="button"
            onClick={() => onFilter(f.key)}
            className={cn(
              "rounded-full border px-3 py-1 text-xs",
              f.key === active ? "border-primary bg-primary/10 text-primary" : "text-muted-foreground hover:text-foreground",
            )}
          >
            {f.label} <span className="opacity-70">{f.count}</span>
          </button>
        ))}
      </div>
    </div>
  )
}

const BAR_COLORS = ["bg-emerald-500", "bg-sky-500", "bg-amber-400", "bg-orange-500", "bg-red-600"]

/** Aging (or any buckets) as one stacked bar with a legend: share by amount. */
export function StackedBar({ items, currency }: { items: { label: string; amount: string; count: number }[]; currency?: string | null }) {
  const total = items.reduce((t, i) => t + Number(i.amount), 0)
  return (
    <div>
      <div className="flex h-3 overflow-hidden rounded-full bg-secondary" role="img" aria-label="Aging by amount">
        {items.map((i, n) =>
          Number(i.amount) > 0 ? (
            <div key={i.label} className={BAR_COLORS[n % BAR_COLORS.length]} style={{ width: `${(100 * Number(i.amount)) / (total || 1)}%` }} title={`${i.label}: ${fmt(i.amount, currency)}`} />
          ) : null,
        )}
      </div>
      <ul className="mt-2 space-y-0.5 text-xs">
        {items.map((i, n) => (
          <li key={i.label} className="flex items-center gap-2 tabular-nums">
            <span className={cn("size-2 rounded-full", BAR_COLORS[n % BAR_COLORS.length])} aria-hidden />
            <span className="w-14">{i.label}</span>
            <span className="ml-auto">{fmt(i.amount, currency)}</span>
            <span className="w-8 text-right text-muted-foreground">{i.count}</span>
          </li>
        ))}
      </ul>
    </div>
  )
}
