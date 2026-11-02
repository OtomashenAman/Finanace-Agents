import { useState } from "react"
import { Link, Navigate, useSearchParams } from "react-router"
import { ArrowRight } from "lucide-react"

import { AppPage } from "@/components/layout/app-page"
import { Button } from "@/components/ui/button"

import type { MessageStatus } from "./api"
import { TaskRow } from "./components/case-extras"
import { TaskActions } from "./components/task-actions"
import { Card, Empty, LoadError, Loading, Pill, PodTabs } from "./components/bits"
import { selectClass } from "./ui"
import { useMessages, useMyQueue, useWorkflows } from "./hooks"
import { formatDateTime, MESSAGE_STATUS, REVIEW_KIND, WORKFLOW_SHORT } from "./labels"

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
    <AppPage title="Service POD" subtitle="Everything waiting on you, across all cases.">
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
            <ul className="divide-y">
              {show("signoff") &&
                q.signoffs.map((c) => {
                  const as = workflows?.find((w) => w.key === c.workflow)?.signoff_as ?? "Finance Admin"
                  return (
                    <li key={c.id} className="flex items-start gap-3 py-3 text-sm">
                      <div className="min-w-0 flex-1">
                        <p className="flex flex-wrap items-center gap-2">
                          <Pill label="Sign-off" tone="good" />
                          <span className="font-semibold">{c.reference}</span>
                          <span>{c.title}</span>
                          <span className="text-xs text-muted-foreground">{WORKFLOW_SHORT[c.workflow]}</span>
                        </p>
                        <p className="mt-1 text-muted-foreground">
                          {as === "Finance Admin" ? "Everything is settled: approve the case" : `Everything is settled: sign off as ${as}`}
                        </p>
                      </div>
                      <OpenButton to={`/pod/cases/${c.id}`} />
                    </li>
                  )
                })}
              {show("review") &&
                q.reviews.map((item) => (
                  <li key={item.task.id} className="flex items-start gap-3 py-3 text-sm">
                    <div className="min-w-0 flex-1">
                      <p className="flex flex-wrap items-center gap-2">
                        <Pill label={`Review · ${REVIEW_KIND[item.task.kind]}`} tone={item.task.blocking ? "warn" : "info"} />
                        <span className="font-semibold">{item.case_reference}</span>
                        <span>{item.case_title}</span>
                        <span className="text-xs text-muted-foreground">{WORKFLOW_SHORT[item.workflow]}</span>
                      </p>
                      <p className="mt-1 text-muted-foreground">
                        {item.task.subject && <strong className="text-foreground">{item.task.subject}: </strong>}
                        {item.task.detail}
                      </p>
                    </div>
                    <OpenButton to={`/pod/cases/${item.case_id}`} />
                  </li>
                ))}
              {show("email") &&
                q.emails.map((m) => (
                  <li key={m.id} className="flex items-start gap-3 py-3 text-sm">
                    <div className="min-w-0 flex-1">
                      <p className="flex flex-wrap items-center gap-2">
                        <Pill label="Email" tone={m.status === "draft" ? "neutral" : "bad"} />
                        <span className="font-semibold">{m.case_reference}</span>
                        <span>{m.subject}</span>
                      </p>
                      <p className="mt-1 text-muted-foreground">
                        {EMAIL_TODO[m.status]} · to {m.to_email} · {formatDateTime(m.updated_at)}
                      </p>
                    </div>
                    <OpenButton to={`/pod/cases/${m.case_id}`} />
                  </li>
                ))}
              {show("posting") &&
                q.postings.map((t) => (
                  <li key={t.id} className="py-3 text-sm">
                    <div className="flex items-start gap-3">
                      <div className="min-w-0 flex-1">
                        <TaskRow t={t} />
                        <p className="text-xs text-muted-foreground">
                          {t.case_reference} · {WORKFLOW_SHORT[t.workflow]} · proposed by {t.proposed_by}
                        </p>
                      </div>
                      <OpenButton to={`/pod/cases/${t.case_id}`} />
                    </div>
                    <details className="mt-1">
                      <summary className="cursor-pointer text-xs text-muted-foreground">What to post</summary>
                      <pre className="mt-1 max-h-32 overflow-auto rounded bg-secondary/40 p-2 text-xs">{JSON.stringify(t.instructions, null, 2)}</pre>
                    </details>
                    <TaskActions t={t} />
                  </li>
                ))}
            </ul>
          </>
        )}
      </Card>
    </AppPage>
  )
}

/** Old addresses (Inbox, AI Review, Manual QB Tasks) land on the matching part of My Queue. */
export function LegacyQueue({ type }: { type: QueueType }) {
  return <Navigate to={`/pod/queue?type=${type}`} replace />
}
