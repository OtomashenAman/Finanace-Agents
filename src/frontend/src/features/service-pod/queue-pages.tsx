import { useState } from "react"
import { Link } from "react-router"

import { AppPage } from "@/components/layout/app-page"

import type { MessageStatus, TaskStatus } from "./api"
import { TaskRow } from "./components/case-extras"
import { TaskActions } from "./components/task-actions"
import { Card, Empty, LoadError, Loading, Pill, PodTabs } from "./components/bits"
import { selectClass } from "./ui"
import { useMessages, useReviewQueue, useTasks } from "./hooks"
import { formatDateTime, MESSAGE_STATUS, REVIEW_KIND, WORKFLOW_SHORT } from "./labels"

/** Every message on the cases: drafts to send, sends to reconcile, replies. */
export function InboxPage() {
  const [status, setStatus] = useState<MessageStatus | "">("")
  const messages = useMessages(status || null)
  return (
    <AppPage title="Service POD" subtitle="Outbound messages and imported customer replies on your cases.">
      <PodTabs />
      <Card
        title="Inbox"
        actions={
          <select className={`${selectClass} w-auto`} value={status} onChange={(e) => setStatus(e.target.value as MessageStatus | "")} aria-label="Status">
            <option value="">All messages</option>
            {Object.entries(MESSAGE_STATUS).map(([k, [label]]) => (
              <option key={k} value={k}>
                {label}
              </option>
            ))}
          </select>
        }
      >
        {messages.isPending && <Loading what="messages" />}
        {messages.isError && <LoadError what="messages" />}
        {messages.data?.length === 0 && <Empty>No messages.</Empty>}
        <ul className="divide-y">
          {messages.data?.map((m) => {
            const [label, tone] = MESSAGE_STATUS[m.status]
            return (
              <li key={m.id} className="flex flex-col gap-1 py-3 text-sm sm:flex-row sm:items-center sm:gap-3">
                <Pill label={label} tone={tone} />
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
      </Card>
    </AppPage>
  )
}

/** Open review tasks: what a person must settle before anything is approved. */
export function ReviewQueuePage() {
  const queue = useReviewQueue()
  return (
    <AppPage
      title="Service POD"
      subtitle="Unknown dates, disputes, missing documents and other ambiguities waiting for a person."
    >
      <PodTabs />
      <Card title="AI Review" hint="Raised by people now; by reply understanding and the workflow engines in the next phases.">
        {queue.isPending && <Loading what="the review queue" />}
        {queue.isError && <LoadError what="the review queue" />}
        {queue.data?.length === 0 && <Empty>Nothing waiting.</Empty>}
        <ul className="divide-y">
          {queue.data?.map((item) => (
            <li key={item.task.id} className="py-3 text-sm">
              <p className="flex flex-wrap items-center gap-2">
                <Pill label={REVIEW_KIND[item.task.kind]} tone={item.task.blocking ? "warn" : "info"} />
                <Link to={`/pod/cases/${item.case_id}`} className="font-semibold text-primary hover:underline">
                  {item.case_reference}
                </Link>
                <span>{item.case_title}</span>
                <span className="text-xs text-muted-foreground">{WORKFLOW_SHORT[item.workflow]}</span>
              </p>
              <p className="mt-1">
                {item.task.subject && <strong>{item.task.subject}: </strong>}
                {item.task.detail}
              </p>
            </li>
          ))}
        </ul>
      </Card>
    </AppPage>
  )
}

/** The manual QuickBooks queue: post outside the application, record, verify. */
export function TasksPage() {
  const [status, setStatus] = useState<TaskStatus | "">("")
  const tasks = useTasks(status || null)
  return (
    <AppPage
      title="Service POD"
      subtitle="Post in QuickBooks yourself, record the transaction ID, then verify it against a fresh export."
    >
      <PodTabs />
      <Card
        title="Manual QB Tasks"
        actions={
          <select className={`${selectClass} w-auto`} value={status} onChange={(e) => setStatus(e.target.value as TaskStatus | "")} aria-label="Status">
            <option value="">All tasks</option>
            <option value="proposed">Proposed</option>
            <option value="approved">To post</option>
            <option value="recorded_unverified">To verify</option>
            <option value="verified">Verified</option>
          </select>
        }
      >
        {tasks.isPending && <Loading what="tasks" />}
        {tasks.isError && <LoadError what="tasks" />}
        {tasks.data?.length === 0 && <Empty>No posting tasks.</Empty>}
        <ul className="divide-y">
          {tasks.data?.map((t) => (
            <li key={t.id} className="py-3 text-sm">
              <TaskRow t={t} />
              <p className="text-xs text-muted-foreground">
                {t.case_reference} · {WORKFLOW_SHORT[t.workflow]} · proposed by {t.proposed_by}
              </p>
              <pre className="mt-1 max-h-32 overflow-auto rounded bg-secondary/40 p-2 text-xs">
                {JSON.stringify(t.instructions, null, 2)}
              </pre>
              <TaskActions t={t} />
            </li>
          ))}
        </ul>
      </Card>
    </AppPage>
  )
}
