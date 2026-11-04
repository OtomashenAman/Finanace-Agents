import { useState } from "react"
import { Link, Navigate, useSearchParams } from "react-router"
import { ArrowRight, Sparkles } from "lucide-react"

import { Button } from "@/components/ui/button"

import type { MessageStatus } from "./api"
import { TaskRow } from "./components/case-extras"
import { TaskActions } from "./components/task-actions"
import { Card, Empty, LoadError, Loading, Pill, PodTabs } from "./components/bits"
import { selectClass } from "./ui"
import { useMessages, useMyQueue, useWorkflows } from "./hooks"
import { formatDateTime, MESSAGE_STATUS, REVIEW_KIND, WORKFLOW_SHORT } from "./labels"
import { PodPage } from "./components/pod-page"

type QueueType = "all" | "signoff" | "review" | "email" | "posting" | "log"

const chip = (on: boolean) =>
  `rounded-full border px-3 py-1 text-xs font-medium transition-colors ${on ? "border-primary bg-primary/10 text-primary" : "bg-card text-muted-foreground hover:text-foreground"}`

function OpenButton({ to }: { to: string }) {
  return (
    <Button asChild size="sm" variant="outline" className="shrink-0">
      <Link to={to}>
        Open <ArrowRight />
      </Link>
    </Button>
  )
}

const EMAIL_TODO: Partial<Record<MessageStatus, string>> = {
  draft: "Check and send this draft",
  send_failed: "Sending failed: fix it and send again",
  send_unknown: "Send outcome unknown: reconcile it",
}

/** Every message on the cases (the full log, not only what needs you). */
function EmailLog() {
  const [status, setStatus] = useState<MessageStatus | "">("")
  const messages = useMessages(status || null)
  return (
    <>
      <div className="mb-3 flex justify-end">
        <select className={`${selectClass} w-auto`} value={status} onChange={(e) => setStatus(e.target.value as MessageStatus | "")} aria-label="Status">
          <option value="">All messages</option>
          {Object.entries(MESSAGE_STATUS).map(([k, [label]]) => (
            <option key={k} value={k}>
              {label}
            </option>
          ))}
        </select>
      </div>
      {messages.isPending && <Loading what="messages" />}
      {messages.isError && <LoadError what="messages" />}
      {messages.data?.length === 0 && <Empty>No messages.</Empty>}
      <ul className="divide-y">
        {messages.data?.map((m) => {
          const [label, tone] = MESSAGE_STATUS[m.status]
          return (
            <li key={m.id} className="flex flex-col gap-1 py-3 text-sm sm:flex-row sm:items-center sm:gap-3">
              <Pill label={label} tone={tone} />
              {m.extraction_status === "case_closed" && <Pill label="After the case closed" tone="warn" />}
              <Link to={`/pod/cases/${m.case_id}`} className="min-w-0 flex-1 truncate font-medium text-primary hover:underline">
                {m.subject}
              </Link>
              <span className="text-xs text-muted-foreground">
                {m.direction === "inbound" ? `from ${m.from_email}` : `to ${m.to_email}`} · {formatDateTime(m.updated_at)}
              </span>
            </li>
          )
        })}
      </ul>
    </>
  )
}

/** One list of what waits on you: review tasks, emails to send, QuickBooks postings. */
export function MyQueuePage() {
  const [params, setParams] = useSearchParams()
  const type = (params.get("type") as QueueType | null) ?? "all"
  const q = useMyQueue()
  // Many cases waiting only for a sign-off read as one line in "Everything"
  const [unfold, setUnfold] = useState(false)
  const folded = type === "all" && !unfold && q.signoffs.length > 2
  const { data: workflows } = useWorkflows()
  const show = (t: QueueType) => type === "all" || type === t
  const tabs: [QueueType, string, number | null][] = [
    ["all", "Everything", q.count],
    ["signoff", "Sign-offs", q.signoffs.length],
    ["review", "Review tasks", q.reviews.length],
    ["email", "Emails to send", q.emails.length],
    ["posting", "QuickBooks postings", q.postings.length],
    ["log", "Email log", null],
  ]

  return (
    <PodPage title="My Queue" subtitle="Everything waiting on you, across all cases.">
      <PodTabs />
      <Card title="My Queue" hint="Settle review tasks, send the emails, and post in QuickBooks by hand: each item opens where it's done.">
        <div className="mb-4 flex flex-wrap gap-1.5" role="group" aria-label="Show">
          {tabs.map(([key, label, n]) => (
            <button key={key} type="button" className={chip(type === key)} onClick={() => setParams(key === "all" ? {} : { type: key }, { replace: true })}>
              {label}
              {n !== null && <span className="ml-1 opacity-70">{n}</span>}
            </button>
          ))}
        </div>

        {type === "log" ? (
          <EmailLog />
        ) : (
          <>
            {q.isPending && <Loading what="your queue" />}
            {q.isError && <LoadError what="your queue" />}
            {!q.isPending && q.count === 0 && <Empty>Nothing is waiting on you.</Empty>}
            <div className="space-y-3">
              {folded && (
                <div className="flex items-center justify-between gap-3 rounded-lg border border-emerald-500/30 bg-emerald-50/50 p-3.5 text-sm dark:bg-emerald-950/20">
                  <div className="flex items-center gap-2.5">
                    <span className="flex size-7 shrink-0 items-center justify-center rounded-md bg-emerald-500/10 text-emerald-700">
                      <Sparkles className="size-4" />
                    </span>
                    <div>
                      <p className="font-semibold text-foreground">
                        {q.signoffs.length} AI cases settled and ready for sign-off
                      </p>
                      <p className="text-xs text-muted-foreground">
                        {q.signoffs.slice(0, 4).map((c) => c.reference).join(", ")}{q.signoffs.length > 4 ? "…" : ""}
                      </p>
                    </div>
                  </div>
                  <Button size="sm" variant="outline" className="border-emerald-600/40 text-emerald-800 hover:bg-emerald-100/50" onClick={() => setUnfold(true)}>
                    Show all ({q.signoffs.length})
                  </Button>
                </div>
              )}
              {show("signoff") &&
                !folded &&
                q.signoffs.map((c) => {
                  const as = workflows?.find((w) => w.key === c.workflow)?.signoff_as ?? "Finance Admin"
                  return (
                    <div
                      key={c.id}
                      className="group flex flex-col sm:flex-row sm:items-center justify-between gap-3 rounded-lg border border-emerald-500/30 bg-card p-3.5 shadow-2xs transition-all hover:border-emerald-500/60 hover:shadow-xs"
                    >
                      <div className="min-w-0 flex-1 space-y-1">
                        <div className="flex flex-wrap items-center gap-2">
                          <span className="inline-flex items-center gap-1 rounded-md bg-emerald-500/10 px-2 py-0.5 text-xs font-semibold text-emerald-700">
                            <Sparkles className="size-3" /> Ready for Sign-off
                          </span>
                          <span className="font-mono text-xs font-bold text-foreground">{c.reference}</span>
                          <span className="rounded bg-secondary/80 px-2 py-0.5 text-xs font-medium text-muted-foreground">
                            {WORKFLOW_SHORT[c.workflow]}
                          </span>
                        </div>
                        <p className="font-semibold text-foreground">{c.title}</p>
                        <p className="text-xs text-muted-foreground">
                          {as === "Finance Admin"
                            ? "All AI calculations verified against read-only QuickBooks snapshot. Awaiting your approval."
                            : `Calculations complete: sign off in your capacity as ${as}.`}
                        </p>
                      </div>
                      <Button asChild size="sm" className="bg-emerald-700 hover:bg-emerald-800 text-white shrink-0">
                        <Link to={`/pod/cases/${c.id}`}>
                          Sign off <ArrowRight className="ml-1 size-3.5" />
                        </Link>
                      </Button>
                    </div>
                  )
                })}
              {show("review") &&
                q.reviews.map((item) => (
                  <div
                    key={item.task.id}
                    className={`group flex flex-col sm:flex-row sm:items-start justify-between gap-3 rounded-lg border p-3.5 shadow-2xs transition-all hover:shadow-xs ${
                      item.task.blocking
                        ? "border-amber-500/40 bg-amber-50/20 hover:border-amber-500/70"
                        : "border-border/70 bg-card hover:border-primary/40"
                    }`}
                  >
                    <div className="min-w-0 flex-1 space-y-1">
                      <div className="flex flex-wrap items-center gap-2">
                        <Pill
                          label={`Review · ${REVIEW_KIND[item.task.kind]}`}
                          tone={item.task.blocking ? "warn" : "info"}
                        />
                        {item.task.blocking && (
                          <span className="rounded bg-amber-500/15 px-1.5 py-0.5 text-[10px] font-semibold text-amber-800">
                            BLOCKS APPROVAL
                          </span>
                        )}
                        <span className="font-mono text-xs font-bold text-foreground">{item.case_reference}</span>
                        <span className="rounded bg-secondary/80 px-2 py-0.5 text-xs font-medium text-muted-foreground">
                          {WORKFLOW_SHORT[item.workflow]}
                        </span>
                      </div>
                      <p className="font-medium text-foreground">{item.case_title}</p>
                      <p className="text-xs text-muted-foreground">
                        {item.task.subject && <strong className="text-foreground">{item.task.subject}: </strong>}
                        {item.task.detail}
                      </p>
                    </div>
                    <Button asChild size="sm" variant="outline" className="shrink-0">
                      <Link to={`/pod/cases/${item.case_id}`}>
                        Resolve in Case <ArrowRight className="ml-1 size-3.5" />
                      </Link>
                    </Button>
                  </div>
                ))}
              {show("email") &&
                q.emails.map((m) => (
                  <div
                    key={m.id}
                    className="group flex flex-col sm:flex-row sm:items-start justify-between gap-3 rounded-lg border border-ai-border/70 bg-card p-3.5 shadow-2xs transition-all hover:border-ai/50 hover:shadow-xs"
                  >
                    <div className="min-w-0 flex-1 space-y-1">
                      <div className="flex flex-wrap items-center gap-2">
                        <span className="inline-flex items-center gap-1 rounded-md bg-ai-soft px-2 py-0.5 text-xs font-semibold text-ai-foreground">
                          <Sparkles className="size-3" /> AI Draft Email
                        </span>
                        <span className="font-mono text-xs font-bold text-foreground">{m.case_reference}</span>
                        <span className="text-xs text-muted-foreground">to {m.to_email}</span>
                      </div>
                      <p className="font-medium text-foreground">{m.subject}</p>
                      <p className="text-xs text-muted-foreground">
                        {EMAIL_TODO[m.status]} · Updated {formatDateTime(m.updated_at)}
                      </p>
                    </div>
                    <Button asChild size="sm" variant="outline" className="border-ai-border text-ai hover:bg-ai-soft shrink-0">
                      <Link to={`/pod/cases/${m.case_id}`}>
                        Review Draft <ArrowRight className="ml-1 size-3.5" />
                      </Link>
                    </Button>
                  </div>
                ))}
              {show("posting") &&
                q.postings.map((t) => (
                  <div
                    key={t.id}
                    className="rounded-lg border border-border/70 bg-card p-3.5 shadow-2xs transition-all hover:border-primary/40 hover:shadow-xs"
                  >
                    <div className="flex flex-col sm:flex-row sm:items-start justify-between gap-3">
                      <div className="min-w-0 flex-1 space-y-1">
                        <div className="flex flex-wrap items-center gap-2">
                          <span className="inline-flex items-center gap-1 rounded-md bg-sky-500/10 px-2 py-0.5 text-xs font-semibold text-sky-700">
                            QuickBooks Manual Post
                          </span>
                          <span className="font-mono text-xs font-bold text-foreground">{t.case_reference}</span>
                          <span className="rounded bg-secondary/80 px-2 py-0.5 text-xs font-medium text-muted-foreground">
                            {WORKFLOW_SHORT[t.workflow]}
                          </span>
                        </div>
                        <TaskRow t={t} />
                        <p className="text-xs text-muted-foreground">
                          Proposed by AI agent · Pending Finance Admin write into QuickBooks
                        </p>
                      </div>
                      <OpenButton to={`/pod/cases/${t.case_id}`} />
                    </div>
                    <details className="mt-2 rounded-md bg-secondary/30 p-2 text-xs">
                      <summary className="cursor-pointer font-medium text-muted-foreground hover:text-foreground">
                        View Posting Payload
                      </summary>
                      <pre className="mt-1.5 max-h-36 overflow-auto rounded bg-secondary/60 p-2 font-mono text-[11px]">
                        {JSON.stringify(t.instructions, null, 2)}
                      </pre>
                    </details>
                    <div className="mt-2 pt-2 border-t border-border/50">
                      <TaskActions t={t} />
                    </div>
                  </div>
                ))}
            </div>
          </>
        )}
      </Card>
    </PodPage>
  )
}

/** Old addresses (Inbox, AI Review, Manual QB Tasks) land on the matching part of My Queue. */
export function LegacyQueue({ type }: { type: QueueType }) {
  return <Navigate to={`/pod/queue?type=${type}`} replace />
}
