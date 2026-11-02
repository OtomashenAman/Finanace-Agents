import { useState } from "react"

import { cn } from "@/lib/utils"

import type { FpaChange, FpaMetric } from "./meta"
import { amount, monthLabel, num, signed } from "./meta"

// Categorical slots 1-3 (validated: light and dark steps); text never wears these colours
const SERIES = [
  { key: "revenue", label: "Revenue", stroke: "stroke-[#2a78d6] dark:stroke-[#3987e5]", fill: "fill-[#2a78d6] dark:fill-[#3987e5]" },
  { key: "cost_of_services", label: "Cost of services", stroke: "stroke-[#eb6834] dark:stroke-[#d95926]", fill: "fill-[#eb6834] dark:fill-[#d95926]" },
  { key: "operating_expense", label: "Operating expenses", stroke: "stroke-[#1baf7a] dark:stroke-[#199e70]", fill: "fill-[#1baf7a] dark:fill-[#199e70]" },
] as const

const W = 640
const H = 260
const PAD = { top: 16, right: 92, bottom: 28, left: 56 }

function niceMax(max: number): number {
  if (max <= 0) return 1
  const step = 10 ** Math.floor(Math.log10(max))
  return Math.ceil((max * 1.08) / step) * step
}

const short = (n: number) =>
  Math.abs(n) >= 1_000_000 ? `${(n / 1_000_000).toFixed(1)}M` : Math.abs(n) >= 1000 ? `${Math.round(n / 1000)}k` : String(n)

/** Revenue, cost of services and operating expenses by month: one axis, three thin lines,
 *  a legend plus end labels, and a crosshair tooltip per month. */
export function TrendChart({ metrics, currency }: { metrics: FpaMetric[]; currency: string }) {
  const [hover, setHover] = useState<number | null>(null)
  const values = metrics.flatMap((m) => SERIES.map((s) => num(m[s.key]) ?? 0))
  const top = niceMax(Math.max(...values, 0))
  const innerW = W - PAD.left - PAD.right
  const innerH = H - PAD.top - PAD.bottom
  const x = (i: number) => PAD.left + (metrics.length === 1 ? innerW / 2 : (i * innerW) / (metrics.length - 1))
  const y = (v: number) => PAD.top + innerH - (Math.max(v, 0) / top) * innerH
  const ticks = [0, 0.25, 0.5, 0.75, 1].map((f) => f * top)
  const last = metrics.length - 1
  const step = metrics.length > 1 ? innerW / (metrics.length - 1) : innerW

  return (
    <figure className="relative">
      <ul className="mb-2 flex flex-wrap gap-4 text-xs text-muted-foreground" aria-label="Legend">
        {SERIES.map((s) => (
          <li key={s.key} className="flex items-center gap-1.5">
            <svg width="16" height="8" aria-hidden>
              <line x1="0" y1="4" x2="16" y2="4" strokeWidth="2" className={s.stroke} />
            </svg>
            {s.label}
          </li>
        ))}
      </ul>
      <svg viewBox={`0 0 ${W} ${H}`} className="w-full" role="img" aria-label={`Monthly revenue and costs, ${currency}`}>
        {ticks.map((t) => (
          <g key={t}>
            <line x1={PAD.left} x2={W - PAD.right} y1={y(t)} y2={y(t)} className="stroke-border" strokeWidth="1" />
            <text x={PAD.left - 8} y={y(t) + 4} textAnchor="end" className="fill-muted-foreground text-[11px]">
              {short(t)}
            </text>
          </g>
        ))}
        {metrics.map((m, i) => (
          <text key={m.period} x={x(i)} y={H - 8} textAnchor="middle" className="fill-muted-foreground text-[11px]">
            {monthLabel(m.period, true)}
          </text>
        ))}
        {hover !== null && <line x1={x(hover)} x2={x(hover)} y1={PAD.top} y2={PAD.top + innerH} className="stroke-muted-foreground/50" strokeWidth="1" />}
        {SERIES.map((s) => (
          <g key={s.key}>
            <polyline
              fill="none"
              strokeWidth="2"
              strokeLinejoin="round"
              className={s.stroke}
              points={metrics.map((m, i) => `${x(i)},${y(num(m[s.key]) ?? 0)}`).join(" ")}
            />
            {metrics.map((m, i) => (
              <circle
                key={m.period}
                cx={x(i)}
                cy={y(num(m[s.key]) ?? 0)}
                r={hover === i ? 5 : 4}
                strokeWidth="2"
                className={cn(s.fill, "stroke-card")}
              />
            ))}
            {last >= 0 && (
              <text x={x(last) + 10} y={y(num(metrics[last]![s.key]) ?? 0) + 4} className="fill-foreground text-[11px] font-medium">
                {short(num(metrics[last]![s.key]) ?? 0)}
              </text>
            )}
          </g>
        ))}
        {metrics.map((m, i) => (
          <rect
            key={m.period}
            x={x(i) - step / 2}
            y={PAD.top}
            width={step}
            height={innerH}
            fill="transparent"
            onMouseEnter={() => setHover(i)}
            onMouseLeave={() => setHover(null)}
          />
        ))}
      </svg>
      {hover !== null && metrics[hover] && (
        <div
          className="pointer-events-none absolute top-8 z-10 rounded-md border bg-popover px-3 py-2 text-xs shadow-md"
          style={{ left: `${Math.min((x(hover) / W) * 100, 70)}%` }}
        >
          <p className="mb-1 font-semibold">{monthLabel(metrics[hover].period)}</p>
          {SERIES.map((s) => (
            <p key={s.key} className="flex items-center justify-between gap-4">
              <span className="flex items-center gap-1.5 text-muted-foreground">
                <svg width="8" height="8" aria-hidden>
                  <circle cx="4" cy="4" r="4" className={s.fill} />
                </svg>
                {s.label}
              </span>
              <span className="font-medium tabular-nums">{amount(metrics[hover]![s.key], currency)}</span>
            </p>
          ))}
        </div>
      )}
    </figure>
  )
}

/** Operating profit bridge: prior profit, each component's effect, current profit. Bars
 *  float from the running total; increases and decreases are two hues, totals neutral. */
export function BridgeChart({ change, currency }: { change: FpaChange; currency: string }) {
  const b = change.bridge
  const steps = [
    { label: `${monthLabel(change.from, true)} profit`, value: Number(b.from_profit), total: true },
    { label: "Revenue", value: Number(b.revenue), total: false },
    { label: "Cost of services", value: Number(b.cost_of_services), total: false },
    { label: "Operating expenses", value: Number(b.operating_expense), total: false },
    { label: `${monthLabel(change.to, true)} profit`, value: Number(b.to_profit), total: true },
  ]
  let running = 0
  const bars = steps.map((s) => {
    const start = s.total ? 0 : running
    const end = s.total ? s.value : running + s.value
    running = s.total ? s.value : end
    return { ...s, start, end }
  })
  const lo = Math.min(0, ...bars.flatMap((b) => [b.start, b.end]))
  const hi = Math.max(...bars.flatMap((b) => [b.start, b.end]), 1)
  const Wb = 640
  const Hb = 240
  const pad = { top: 24, bottom: 36, left: 12, right: 12 }
  const innerH = Hb - pad.top - pad.bottom
  const slot = (Wb - pad.left - pad.right) / bars.length
  const y = (v: number) => pad.top + ((hi - v) / (hi - lo)) * innerH
  return (
    <svg viewBox={`0 0 ${Wb} ${Hb}`} className="w-full" role="img" aria-label="Operating profit bridge">
      <line x1={pad.left} x2={Wb - pad.right} y1={y(0)} y2={y(0)} className="stroke-border" />
      {bars.map((bar, i) => {
        const top = y(Math.max(bar.start, bar.end))
        const height = Math.max(Math.abs(y(bar.start) - y(bar.end)), 2)
        const cls = bar.total
          ? "fill-slate-400 dark:fill-slate-500"
          : bar.value >= 0
            ? "fill-[#2a78d6] dark:fill-[#3987e5]"
            : "fill-[#eb6834] dark:fill-[#d95926]"
        const cx = pad.left + slot * i + slot / 2
        return (
          <g key={bar.label}>
            <title>{`${bar.label}: ${bar.total ? amount(String(bar.value), currency) : signed(String(bar.value), currency)}`}</title>
            <rect x={cx - slot * 0.28} y={top} width={slot * 0.56} height={height} rx="4" className={cls} />
            <text x={cx} y={top - 6} textAnchor="middle" className="fill-foreground text-[11px] font-medium">
              {bar.total ? short(bar.value) : `${bar.value >= 0 ? "+" : "−"}${short(Math.abs(bar.value))}`}
            </text>
            <text x={cx} y={Hb - 14} textAnchor="middle" className="fill-muted-foreground text-[11px]">
              {bar.label}
            </text>
          </g>
        )
      })}
    </svg>
  )
}
