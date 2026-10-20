import { useState } from "react"

import type { LlmDay } from "../api"

const HEIGHT = 160 // plot height in px

/** Round the axis top up to a clean number (1, 2, 5 × 10ⁿ) so the ticks read easily. */
function niceMax(value: number): number {
  if (value <= 4) return 4
  const power = 10 ** Math.floor(Math.log10(value))
  const step = [1, 2, 5, 10].find((m) => m * power >= value) ?? 10
  return step * power
}

function compact(n: number): string {
  return n >= 1000 ? `${(n / 1000).toFixed(n >= 10_000 ? 0 : 1)}K` : String(n)
}

function dayLabel(day: string, withYear = false): string {
  return new Intl.DateTimeFormat(undefined, {
    day: "numeric",
    month: "short",
    ...(withYear && { year: "numeric" }),
    timeZone: "UTC",
  }).format(new Date(`${day}T00:00:00Z`))
}

function Swatch({ className }: { className: string }) {
  return <span className={`inline-block size-2.5 rounded-sm ${className}`} aria-hidden />
}

/** Calls per day, stacked succeeded / failed, with a hover (and focus) tooltip. */
export function DailyCallsChart({ days }: { days: LlmDay[] }) {
  const [active, setActive] = useState<number | null>(null)
  const top = niceMax(Math.max(0, ...days.map((d) => d.calls)))
  const ticks = [top, top / 2, 0]
  const labelEvery = days.length > 14 ? Math.ceil(days.length / 6) : 1
  const px = (n: number) => (n / top) * HEIGHT

  return (
    <figure className="space-y-3">
      <figcaption className="flex flex-wrap items-center justify-between gap-2">
        <span className="text-sm font-semibold text-brand-navy">AI calls per day</span>
        <span className="flex items-center gap-4 text-xs text-muted-foreground">
          <span className="flex items-center gap-1.5">
            <Swatch className="bg-viz-ok" /> Succeeded
          </span>
          <span className="flex items-center gap-1.5">
            <Swatch className="bg-viz-failed" /> Failed
          </span>
        </span>
      </figcaption>

      <div className="flex gap-2">
        {/* y axis */}
        <div className="relative w-8 shrink-0 text-right text-[11px] text-muted-foreground" style={{ height: HEIGHT }} aria-hidden>
          {ticks.map((t) => (
            <span key={t} className="absolute right-0 -translate-y-1/2" style={{ top: HEIGHT - px(t) }}>
              {compact(t)}
            </span>
          ))}
        </div>

        <div className="min-w-0 flex-1">
          <div className="relative" style={{ height: HEIGHT }}>
            {ticks.map((t) => (
              <div key={t} className="absolute inset-x-0 border-t border-border" style={{ top: HEIGHT - px(t) }} />
            ))}
            <div className="absolute inset-0 flex">
              {days.map((d, i) => {
                const ok = d.calls - d.failed
                return (
                  <div
                    key={d.day}
                    className="relative flex flex-1 cursor-default items-end justify-center outline-none focus-visible:bg-secondary/60"
                    onMouseEnter={() => setActive(i)}
                    onMouseLeave={() => setActive(null)}
                    onFocus={() => setActive(i)}
                    onBlur={() => setActive(null)}
                    tabIndex={0}
                    aria-label={`${dayLabel(d.day)}: ${d.calls} calls, ${d.failed} failed`}
                  >
                    {active === i && <div className="absolute inset-y-0 w-full bg-secondary/50" />}
                    {d.calls > 0 && (
                      <div className="relative flex w-full max-w-6 flex-col-reverse gap-0.5 px-[15%] sm:px-0">
                        {ok > 0 && (
                          <div
                            className="w-full rounded-t-[4px] bg-viz-ok"
                            style={{ height: px(ok), ...(d.failed > 0 && { borderRadius: 0 }) }}
                          />
                        )}
                        {d.failed > 0 && (
                          <div className="w-full rounded-t-[4px] bg-viz-failed" style={{ height: Math.max(px(d.failed) - 2, 2) }} />
                        )}
                      </div>
                    )}
                    {active === i && (
                      <div
                        role="tooltip"
                        className="pointer-events-none absolute z-10 w-max -translate-y-2 rounded-md border bg-card px-3 py-2 text-xs shadow-md"
                        style={{
                          bottom: Math.min(px(d.calls), HEIGHT - 70) + 8,
                          ...(i > days.length / 2 ? { right: 0 } : { left: 0 }),
                        }}
                      >
                        <p className="font-semibold text-foreground">{dayLabel(d.day, true)}</p>
                        <p className="mt-1 flex items-center gap-1.5 text-foreground">
                          <Swatch className="bg-viz-ok" /> {ok} succeeded
                        </p>
                        <p className="flex items-center gap-1.5 text-foreground">
                          <Swatch className="bg-viz-failed" /> {d.failed} failed
                        </p>
                        <p className="mt-1 text-muted-foreground">
                          {compact(d.input_tokens + d.output_tokens)} tokens · p95{" "}
                          {d.p95_latency_ms !== null ? `${(d.p95_latency_ms / 1000).toFixed(1)}s` : "—"}
                        </p>
                      </div>
                    )}
                  </div>
                )
              })}
            </div>
          </div>
          {/* x axis */}
          <div className="mt-1.5 flex border-t border-border pt-1.5 text-[11px] text-muted-foreground" aria-hidden>
            {days.map((d, i) => (
              <span key={d.day} className="flex-1 text-center whitespace-nowrap">
                {i % labelEvery === 0 || i === days.length - 1 ? dayLabel(d.day) : ""}
              </span>
            ))}
          </div>
        </div>
      </div>

      {/* Same data for screen readers and anyone who prefers numbers */}
      <table className="sr-only">
        <caption>AI calls per day</caption>
        <thead>
          <tr>
            <th>Day</th>
            <th>Calls</th>
            <th>Failed</th>
            <th>Tokens</th>
            <th>p95 latency (ms)</th>
          </tr>
        </thead>
        <tbody>
          {days.map((d) => (
            <tr key={d.day}>
              <td>{d.day}</td>
              <td>{d.calls}</td>
              <td>{d.failed}</td>
              <td>{d.input_tokens + d.output_tokens}</td>
              <td>{d.p95_latency_ms ?? "—"}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </figure>
  )
}
