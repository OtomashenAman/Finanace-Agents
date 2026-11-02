import { useState } from "react"

import { cn } from "@/lib/utils"

import { amount, monthLabel } from "../fpa-trend/meta"
import type { ForecastResult, ScenarioName } from "./meta"
import { SCENARIO_LABEL } from "./meta"

// Categorical slots 1-3 (validated light and dark steps); the buffer is a neutral reference line
const SERIES: Record<ScenarioName, { stroke: string; fill: string }> = {
  base: { stroke: "stroke-[#2a78d6] dark:stroke-[#3987e5]", fill: "fill-[#2a78d6] dark:fill-[#3987e5]" },
  stress: { stroke: "stroke-[#eb6834] dark:stroke-[#d95926]", fill: "fill-[#eb6834] dark:fill-[#d95926]" },
  optimistic: { stroke: "stroke-[#1baf7a] dark:stroke-[#199e70]", fill: "fill-[#1baf7a] dark:fill-[#199e70]" },
}
// Legend and tooltip order; Base is drawn last so it stays on top where the lines overlap
const ORDER: ScenarioName[] = ["base", "stress", "optimistic"]
const DRAW: ScenarioName[] = ["optimistic", "stress", "base"]

/** A round axis top (e.g. 324k -> 350k) */
function nice(value: number): number {
  if (value <= 0) return 0
  const step = 10 ** Math.floor(Math.log10(value)) / 2
  return Math.ceil(value / step) * step
}

const W = 680
const H = 260
const PAD = { top: 14, right: 86, bottom: 26, left: 56 }

const short = (n: number) => (Math.abs(n) >= 1_000_000 ? `${(n / 1_000_000).toFixed(1)}M` : Math.abs(n) >= 1000 ? `${Math.round(n / 1000)}k` : String(Math.round(n)))

/** Daily cash over the 91 days for each scenario, with the policy buffer as a dashed line. */
export function CashChart({ results, currency }: { results: Record<ScenarioName, ForecastResult>; currency: string }) {
  const [hover, setHover] = useState<number | null>(null)
  const base = results.base
  const days = base.days
  const buffer = Number(base.buffer)
  const values = ORDER.flatMap((s) => results[s].days.map((d) => Number(d.cash))).concat([buffer, Number(base.opening), 0])
  // Round ticks: a round step, the axis from zero (or below, if cash goes negative)
  const step = nice((Math.max(...values) - Math.min(0, ...values)) / 4) || 1
  const lo = Math.floor(Math.min(0, ...values) / step) * step
  const hi = Math.ceil((Math.max(...values) * 1.03) / step) * step
  const innerW = W - PAD.left - PAD.right
  const innerH = H - PAD.top - PAD.bottom
  const x = (i: number) => PAD.left + (i * innerW) / (days.length - 1)
  const y = (v: number) => PAD.top + ((hi - v) / (hi - lo || 1)) * innerH
  const ticks = Array.from({ length: Math.round((hi - lo) / step) + 1 }, (_, i) => lo + i * step)
  const months = days.map((d, i) => [d.date, i] as const).filter(([d]) => d.endsWith("-01"))
  const last = days.length - 1

  return (
    <figure className="relative">
      <ul className="mb-2 flex flex-wrap gap-4 text-xs text-muted-foreground" aria-label="Legend">
        {ORDER.map((s) => (
          <li key={s} className="flex items-center gap-1.5">
            <svg width="16" height="8" aria-hidden>
              <line x1="0" y1="4" x2="16" y2="4" strokeWidth="2" className={SERIES[s].stroke} />
            </svg>
            {SCENARIO_LABEL[s]}
          </li>
        ))}
        <li className="flex items-center gap-1.5">
          <svg width="16" height="8" aria-hidden>
            <line x1="0" y1="4" x2="16" y2="4" strokeWidth="1.5" strokeDasharray="3 3" className="stroke-muted-foreground" />
          </svg>
          Policy buffer
        </li>
      </ul>
      <svg viewBox={`0 0 ${W} ${H}`} className="w-full" role="img" aria-label={`Daily cash for 91 days, ${currency}`}>
        {ticks.map((t) => (
          <g key={t}>
            <line x1={PAD.left} x2={W - PAD.right} y1={y(t)} y2={y(t)} className="stroke-border" />
            <text x={PAD.left - 8} y={y(t) + 4} textAnchor="end" className="fill-muted-foreground text-[11px]">
              {short(t)}
            </text>
          </g>
        ))}
        {months.map(([d, i]) => (
          <text key={d} x={x(i)} y={H - 8} textAnchor="middle" className="fill-muted-foreground text-[11px]">
            {monthLabel(d.slice(0, 7), true)}
          </text>
        ))}
        <line x1={PAD.left} x2={W - PAD.right} y1={y(buffer)} y2={y(buffer)} strokeDasharray="4 4" strokeWidth="1.5" className="stroke-muted-foreground" />
        <text x={W - PAD.right + 6} y={y(buffer) + 4} className="fill-muted-foreground text-[11px]">
          buffer
        </text>
        {hover !== null && <line x1={x(hover)} x2={x(hover)} y1={PAD.top} y2={PAD.top + innerH} className="stroke-muted-foreground/50" />}
        {DRAW.map((s) => {
          const pts = results[s].days.map((d, i) => `${x(i)},${y(Number(d.cash))}`).join(" ")
          const end = Number(results[s].days[last]!.cash)
          return (
            <g key={s}>
              <polyline fill="none" strokeWidth="2" strokeLinejoin="round" className={SERIES[s].stroke} points={pts} />
              {hover !== null && <circle cx={x(hover)} cy={y(Number(results[s].days[hover]!.cash))} r="4" strokeWidth="2" className={cn(SERIES[s].fill, "stroke-card")} />}
              <text x={x(last) + 6} y={y(end) + 4} className="fill-foreground text-[11px] font-medium">
                {short(end)}
              </text>
            </g>
          )
        })}
        {days.map((d, i) => (
          <rect key={d.date} x={x(i) - innerW / days.length / 2} y={PAD.top} width={innerW / days.length} height={innerH} fill="transparent" onMouseEnter={() => setHover(i)} onMouseLeave={() => setHover(null)} />
        ))}
      </svg>
      {hover !== null && (
        <div className="pointer-events-none absolute top-8 z-10 rounded-md border bg-popover px-3 py-2 text-xs shadow-md" style={{ left: `${Math.min((x(hover) / W) * 100, 68)}%` }}>
          <p className="mb-1 font-semibold">{days[hover]!.date}</p>
          {ORDER.map((s) => {
            const d = results[s].days[hover]!
            return (
              <p key={s} className="flex items-center justify-between gap-4">
                <span className="flex items-center gap-1.5 text-muted-foreground">
                  <svg width="8" height="8" aria-hidden>
                    <circle cx="4" cy="4" r="4" className={SERIES[s].fill} />
                  </svg>
                  {SCENARIO_LABEL[s]}
                </span>
                <span className={cn("font-medium tabular-nums", Number(d.shortfall) > 0 && "text-red-800")}>{amount(d.cash, currency)}</span>
              </p>
            )
          })}
        </div>
      )}
    </figure>
  )
}
