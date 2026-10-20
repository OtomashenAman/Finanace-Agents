import { useState } from "react"
import { Link } from "react-router"
import { CircleAlert, LoaderCircle } from "lucide-react"

import { AppPage } from "@/components/layout/app-page"
import { Alert } from "@/components/ui/alert"
import { AdminTabs } from "@/features/admin/components/admin-tabs"
import { Panel } from "@/features/agent-catalog/workspace/components/panel"
import { formatDateTime } from "@/features/agent-catalog/workspace/format"
import { cn } from "@/lib/utils"

import type { LlmBreakdown, LlmCall, LlmStatus } from "./api"
import { DailyCallsChart } from "./components/daily-calls-chart"
import { useAiMonitoring } from "./hooks"

const RANGES = [7, 30, 90] as const

const STATUS: Record<LlmStatus, { label: string; tone: string }> = {
  ok: { label: "Succeeded", tone: "bg-emerald-50 text-emerald-800" },
  failed: { label: "Failed", tone: "bg-red-50 text-red-800" },
  not_configured: { label: "Not configured", tone: "bg-muted text-muted-foreground" },
}

const number = (n: number) => n.toLocaleString()
const seconds = (ms: number | null) => (ms === null ? "—" : `${(ms / 1000).toFixed(1)}s`)

function Tile({ label, value, hint, tone }: { label: string; value: string; hint?: string; tone?: "bad" }) {
  return (
    <div className="rounded-lg border bg-card p-4">
      <p className="text-xs font-semibold tracking-wide text-muted-foreground uppercase">{label}</p>
      <p className={cn("mt-1.5 text-2xl font-bold text-brand-navy tabular-nums", tone === "bad" && "text-red-800")}>
        {value}
      </p>
      {hint && <p className="mt-0.5 text-xs text-muted-foreground">{hint}</p>}
    </div>
  )
}

function BreakdownTable({ rows, first }: { rows: LlmBreakdown[]; first: string }) {
  if (!rows.length) return <p className="text-sm text-muted-foreground">No calls in this period.</p>
  return (
    <div className="overflow-x-auto">
      <table className="w-full min-w-[420px] text-sm">
        <thead>
          <tr className="border-b text-left text-xs tracking-wide text-muted-foreground uppercase">
            <th className="py-2 pr-4 font-semibold">{first}</th>
            <th className="py-2 pr-4 text-right font-semibold">Calls</th>
            <th className="py-2 pr-4 text-right font-semibold">Failed</th>
            <th className="py-2 pr-4 text-right font-semibold">Tokens</th>
            <th className="py-2 text-right font-semibold">Avg latency</th>
          </tr>
        </thead>
        <tbody className="divide-y">
          {rows.map((r) => (
            <tr key={r.key}>
              <td className="py-2.5 pr-4 break-all">{r.label}</td>
              <td className="py-2.5 pr-4 text-right tabular-nums">{number(r.calls)}</td>
              <td className={cn("py-2.5 pr-4 text-right tabular-nums", r.failed > 0 && "font-medium text-red-800")}>
                {number(r.failed)}
              </td>
              <td className="py-2.5 pr-4 text-right tabular-nums">{number(r.input_tokens + r.output_tokens)}</td>
              <td className="py-2.5 text-right tabular-nums">{seconds(r.avg_latency_ms)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

function CallsTable({ calls, showError }: { calls: LlmCall[]; showError?: boolean }) {
  return (
    <div className="overflow-x-auto">
      <table className="w-full min-w-[640px] text-sm">
        <thead>
          <tr className="border-b text-left text-xs tracking-wide text-muted-foreground uppercase">
            <th className="py-2 pr-4 font-semibold">Time</th>
            <th className="py-2 pr-4 font-semibold">Run</th>
            <th className="py-2 pr-4 font-semibold">Model</th>
            <th className="py-2 pr-4 text-right font-semibold">Tokens</th>
            <th className="py-2 pr-4 text-right font-semibold">Latency</th>
            <th className="py-2 font-semibold">{showError ? "Error" : "Status"}</th>
          </tr>
        </thead>
        <tbody className="divide-y">
          {calls.map((c) => (
            <tr key={c.id}>
              <td className="py-2.5 pr-4 whitespace-nowrap text-muted-foreground">{formatDateTime(c.created_at)}</td>
              <td className="py-2.5 pr-4 whitespace-nowrap">
                <Link to={`/catalog/${c.run.agent_key}/runs/${c.run.id}`} className="font-medium text-primary hover:underline">
                  {c.run.reference}
                </Link>{" "}
                <span className="text-muted-foreground">{c.run.agent_name}</span>
              </td>
              <td className="py-2.5 pr-4 text-xs break-all">
                {c.model}
                <span className="block text-muted-foreground">{c.prompt_version}</span>
              </td>
              <td className="py-2.5 pr-4 text-right tabular-nums">
                {c.input_tokens === null ? "—" : number(c.input_tokens + (c.output_tokens ?? 0))}
              </td>
              <td className="py-2.5 pr-4 text-right tabular-nums">{seconds(c.latency_ms)}</td>
              <td className="py-2.5">
                {showError ? (
                  <span className="text-red-800">{c.error ?? STATUS[c.status].label}</span>
                ) : (
                  <span className="flex flex-wrap items-center gap-1.5">
                    <span className={cn("rounded px-2 py-0.5 text-xs font-medium", STATUS[c.status].tone)}>
                      {STATUS[c.status].label}
                    </span>
                    {c.guard_warnings.length > 0 && (
                      <span className="text-xs text-amber-800" title={c.guard_warnings.join("\n")}>
                        {c.guard_warnings.length} guard note(s)
                      </span>
                    )}
                  </span>
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

/** Finance Admin view of every AI explanation call: volume, failures, tokens and latency. */
export function AiMonitoringPage() {
  const [days, setDays] = useState<(typeof RANGES)[number]>(7)
  const { data, isPending, isError } = useAiMonitoring(days)

  return (
    <AppPage
      title="Admin Settings · AI monitoring"
      subtitle="Every AI explanation call made while analyzing runs. Calculations and decisions never depend on the model."
    >
      <AdminTabs />
      <div className="space-y-6">
        <div className="flex flex-wrap items-center gap-2" role="group" aria-label="Period">
          {RANGES.map((r) => (
            <button
              key={r}
              type="button"
              onClick={() => setDays(r)}
              aria-pressed={days === r}
              className={cn(
                "rounded-md border px-3 py-1.5 text-sm font-medium",
                days === r ? "border-primary bg-primary text-primary-foreground" : "bg-card hover:bg-secondary",
              )}
            >
              Last {r} days
            </button>
          ))}
        </div>

        {isPending && (
          <div className="flex justify-center py-16" role="status">
            <LoaderCircle className="size-6 animate-spin text-primary" aria-hidden />
            <span className="sr-only">Loading AI monitoring…</span>
          </div>
        )}
        {isError && <Alert>Couldn't load AI monitoring. Refresh the page to try again.</Alert>}

        {data && (
          <>
            <div className="grid grid-cols-2 gap-4 lg:grid-cols-5">
              <Tile label="Calls" value={number(data.totals.calls)} hint={`${number(data.totals.ok)} succeeded`} />
              <Tile
                label="Failure rate"
                value={`${(data.totals.failure_rate * 100).toFixed(data.totals.failure_rate < 0.1 ? 1 : 0)}%`}
                hint={`${number(data.totals.failed)} failed`}
                tone={data.totals.failure_rate >= 0.05 ? "bad" : undefined}
              />
              <Tile label="p95 latency" value={seconds(data.totals.p95_latency_ms)} hint={`avg ${seconds(data.totals.avg_latency_ms)}`} />
              <Tile
                label="Tokens"
                value={number(data.totals.input_tokens + data.totals.output_tokens)}
                hint={`${number(data.totals.input_tokens)} in · ${number(data.totals.output_tokens)} out`}
              />
              <Tile
                label="Guard notes"
                value={number(data.totals.with_guard_warnings)}
                hint="outputs the guard flagged"
              />
            </div>

            {data.totals.not_configured > 0 && (
              <p className="flex items-center gap-2 text-sm text-muted-foreground">
                <CircleAlert className="size-4" aria-hidden />
                {data.totals.not_configured} run(s) were analyzed while the AI provider wasn't configured (no explanation
                was drafted).
              </p>
            )}

            <section className="rounded-lg border bg-card p-5 sm:p-6">
              <DailyCallsChart days={data.daily} />
            </section>

            <div className="grid gap-6 xl:grid-cols-2">
              <Panel title="By model">
                <BreakdownTable rows={data.by_model} first="Model" />
              </Panel>
              <Panel title="By agent">
                <BreakdownTable rows={data.by_agent} first="Agent" />
              </Panel>
            </div>

            <Panel title="Recent failures">
              {data.recent_failures.length ? (
                <CallsTable calls={data.recent_failures} showError />
              ) : (
                <p className="text-sm text-muted-foreground">No failed calls in this period.</p>
              )}
            </Panel>
            <Panel title="Recent calls">
              {data.recent_calls.length ? (
                <CallsTable calls={data.recent_calls} />
              ) : (
                <p className="text-sm text-muted-foreground">No calls in this period.</p>
              )}
            </Panel>
          </>
        )}
      </div>
    </AppPage>
  )
}
