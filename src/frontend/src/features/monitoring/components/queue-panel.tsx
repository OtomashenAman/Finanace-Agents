import { Link } from "react-router"
import { LoaderCircle, RotateCw } from "lucide-react"
import { toast } from "sonner"

import { Alert } from "@/components/ui/alert"
import { Button } from "@/components/ui/button"
import { Panel } from "@/features/agent-catalog/workspace/components/panel"
import { formatDateTime } from "@/features/agent-catalog/workspace/format"
import { errorMessage } from "@/lib/api"
import { cn } from "@/lib/utils"

import type { QueueJob } from "../api"
import { useQueue, useRetryJob } from "../hooks"

const KIND_LABELS: Record<string, string> = {
  "run.narrative": "AI explanation",
  "quickbooks.writeback": "QuickBooks write-back",
}

function wait(seconds: number | null): string {
  if (seconds === null) return "—"
  if (seconds < 60) return `${seconds}s`
  if (seconds < 3600) return `${Math.round(seconds / 60)} min`
  return `${(seconds / 3600).toFixed(1)} h`
}

function JobsTable({ jobs, retry }: { jobs: QueueJob[]; retry?: boolean }) {
  const retryJob = useRetryJob()
  return (
    <div className="overflow-x-auto">
      <table className="w-full min-w-[640px] text-sm">
        <thead>
          <tr className="border-b text-left text-xs tracking-wide text-muted-foreground uppercase">
            <th className="py-2 pr-4 font-semibold">Job</th>
            <th className="py-2 pr-4 font-semibold">Run</th>
            <th className="py-2 pr-4 text-right font-semibold">Attempts</th>
            <th className="py-2 pr-4 font-semibold">{retry ? "Gave up" : "Next try"}</th>
            <th className="py-2 pr-4 font-semibold">Last error</th>
            {retry && <th className="py-2 font-semibold" aria-label="Actions" />}
          </tr>
        </thead>
        <tbody className="divide-y">
          {jobs.map((j) => (
            <tr key={j.id}>
              <td className="py-2.5 pr-4">{KIND_LABELS[j.kind] ?? j.kind}</td>
              <td className="py-2.5 pr-4">
                {j.run_link ? (
                  <Link to={j.run_link} className="font-medium text-primary hover:underline">
                    {j.run_reference}
                  </Link>
                ) : (
                  "—"
                )}
              </td>
              <td className="py-2.5 pr-4 text-right tabular-nums">
                {j.attempts}/{j.max_attempts}
              </td>
              <td className="py-2.5 pr-4 whitespace-nowrap text-muted-foreground">
                {formatDateTime(retry ? j.finished_at : j.run_after)}
              </td>
              <td className="max-w-[320px] py-2.5 pr-4 text-red-800">{j.last_error ?? "—"}</td>
              {retry && (
                <td className="py-2.5">
                  <Button
                    type="button"
                    size="sm"
                    variant="outline"
                    disabled={retryJob.isPending}
                    onClick={() =>
                      retryJob.mutate(j.id, {
                        onSuccess: () => toast.success("Queued again"),
                        onError: (error) => toast.error(errorMessage(error, "Couldn't retry the job")),
                      })
                    }
                  >
                    <RotateCw aria-hidden />
                    Retry
                  </Button>
                </td>
              )}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

/** Background queue health (PDF p.5 "queue failures"): waiting, running, retrying, failed. */
export function QueuePanel() {
  const { data, isPending, isError } = useQueue()

  return (
    <Panel title="Background jobs">
      {isPending && <LoaderCircle className="size-5 animate-spin text-primary" aria-label="Loading" />}
      {isError && <Alert>Couldn't load the job queue.</Alert>}
      {data && (
        <div className="space-y-5">
          <dl className="grid grid-cols-2 gap-4 sm:grid-cols-5">
            {[
              ["Waiting", String(data.queued), false],
              ["Running", String(data.running), false],
              ["Longest wait", wait(data.oldest_queued_seconds), (data.oldest_queued_seconds ?? 0) > 300],
              ["Done (24 h)", String(data.succeeded_24h), false],
              ["Failed", String(data.failed), data.failed > 0],
            ].map(([label, value, bad]) => (
              <div key={String(label)}>
                <dt className="text-xs font-semibold tracking-wide text-muted-foreground uppercase">{label}</dt>
                <dd className={cn("mt-1 text-xl font-bold tabular-nums text-brand-navy", bad && "text-red-800")}>{value}</dd>
              </div>
            ))}
          </dl>
          {(data.oldest_queued_seconds ?? 0) > 300 && (
            <Alert>Jobs have been waiting over 5 minutes: check that the worker is running (python -m src.app.cli.worker).</Alert>
          )}
          {data.failures.length > 0 && (
            <div>
              <h3 className="mb-2 text-sm font-semibold text-brand-navy">Failed (gave up)</h3>
              <JobsTable jobs={data.failures} retry />
            </div>
          )}
          {data.retrying.length > 0 && (
            <div>
              <h3 className="mb-2 text-sm font-semibold text-brand-navy">Retrying</h3>
              <JobsTable jobs={data.retrying} />
            </div>
          )}
          {!data.failures.length && !data.retrying.length && (
            <p className="text-sm text-muted-foreground">No failed or retrying jobs.</p>
          )}
        </div>
      )}
    </Panel>
  )
}
