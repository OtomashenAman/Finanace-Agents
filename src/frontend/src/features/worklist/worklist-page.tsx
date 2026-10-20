import type { ReactNode } from "react"
import { Link } from "react-router"
import {
  CircleCheck,
  CircleCheckBig,
  Database,
  FilePen,
  Hourglass,
  Inbox,
  LoaderCircle,
  Lock,
  Send,
  TriangleAlert,
  Undo2,
  type LucideIcon,
} from "lucide-react"

import { AppPage } from "@/components/layout/app-page"
import { Alert } from "@/components/ui/alert"
import { Button } from "@/components/ui/button"
import { useCurrentUser } from "@/features/auth/hooks"
import { isAdmin } from "@/features/auth/roles"
import { cn } from "@/lib/utils"

import type { WorkItem, WorkKind } from "./api"
import { useWorklist } from "./hooks"

const ICONS: Record<WorkKind, LucideIcon> = {
  approve: CircleCheckBig,
  changes_requested: Undo2,
  validation_failed: TriangleAlert,
  ready_to_submit: Send,
  draft: FilePen,
  data_source: Database,
  locked_account: Lock,
  waiting: Hourglass,
  user_data_source: Database,
}

const KIND_LABELS: Record<WorkKind, string> = {
  approve: "Approval",
  changes_requested: "Changes requested",
  validation_failed: "Validation failed",
  ready_to_submit: "Ready to submit",
  draft: "Draft",
  data_source: "Data source",
  locked_account: "Locked account",
  waiting: "Waiting",
  user_data_source: "User's data source",
}

function age(since: string): string {
  const minutes = Math.max(0, (Date.now() - new Date(since).getTime()) / 60_000)
  if (minutes < 60) return `${Math.round(minutes)} min`
  if (minutes < 48 * 60) return `${Math.round(minutes / 60)} h`
  return `${Math.round(minutes / (24 * 60))} days`
}

function Item({ item }: { item: WorkItem }) {
  const Icon = ICONS[item.kind]
  return (
    <li className="flex flex-col gap-3 py-4 sm:flex-row sm:items-center">
      <span
        className={cn(
          "flex size-9 shrink-0 items-center justify-center rounded-md",
          item.overdue || item.kind === "validation_failed" ? "bg-red-50 text-red-800" : "bg-secondary text-brand-navy",
        )}
        aria-hidden
      >
        <Icon className="size-4" />
      </span>
      <div className="min-w-0 flex-1">
        <p className="flex flex-wrap items-center gap-x-2 gap-y-1">
          <span className="text-xs font-semibold tracking-wide text-muted-foreground uppercase">{KIND_LABELS[item.kind]}</span>
          <span className="font-semibold text-brand-navy">{item.title}</span>
          {item.overdue && (
            <span className="rounded bg-red-50 px-1.5 py-0.5 text-xs font-semibold text-red-800">
              {item.kind === "draft" ? "Stale" : "Overdue"}
            </span>
          )}
          {item.high_priority && <span className="text-xs font-semibold text-red-700">High priority</span>}
        </p>
        {item.detail && <p className="mt-0.5 text-sm">{item.detail}</p>}
        <p className="mt-0.5 text-xs text-muted-foreground">
          {[item.context, `${age(item.since)} ago`].filter(Boolean).join(" · ")}
        </p>
      </div>
      <Button asChild size="sm" variant={item.action_label ? "default" : "outline"} className="shrink-0 self-start sm:self-center">
        <Link to={item.link}>{item.action_label ?? "Open"}</Link>
      </Button>
    </li>
  )
}

function Section({ title, hint, items, empty }: { title: string; hint?: string; items: WorkItem[]; empty?: ReactNode }) {
  return (
    <section className="rounded-lg border bg-card p-5 sm:p-6" aria-label={title}>
      <div className="flex flex-wrap items-baseline justify-between gap-2 border-b pb-3">
        <h2 className="text-lg font-semibold text-brand-navy">
          {title} <span className="text-sm font-normal text-muted-foreground">({items.length})</span>
        </h2>
        {hint && <p className="text-xs text-muted-foreground">{hint}</p>}
      </div>
      {items.length ? <ul className="divide-y">{items.map((i) => <Item key={`${i.kind}-${i.link}-${i.title}`} item={i} />)}</ul> : empty}
    </section>
  )
}

/** Everything that needs the viewer now, most urgent first. */
export function WorklistPage() {
  const { data: user } = useCurrentUser()
  const admin = isAdmin(user)
  const { data, isPending, isError } = useWorklist()

  return (
    <AppPage
      title="My Worklist"
      subtitle={
        admin
          ? "Approvals waiting for you, your own runs to finish and accounts that need help."
          : "Your runs to finish, changes the Finance Admin asked for, and data sources to fix."
      }
    >
      {isPending && (
        <div className="flex justify-center py-16" role="status">
          <LoaderCircle className="size-6 animate-spin text-primary" aria-hidden />
          <span className="sr-only">Loading worklist…</span>
        </div>
      )}
      {isError && <Alert>Couldn't load your worklist. Refresh the page to try again.</Alert>}
      {data && (
        <div className="space-y-6">
          <Section
            title="Needs you"
            hint={`Approvals are overdue after ${data.review_sla_hours} h; drafts are stale after ${data.stale_draft_days} days.`}
            items={data.action}
            empty={
              <div className="flex flex-col items-center gap-2 py-10 text-center">
                <CircleCheck className="size-8 text-emerald-600" aria-hidden />
                <p className="font-medium">You're all caught up</p>
              </div>
            }
          />
          {(data.waiting.length > 0 || !admin) && (
            <Section
              title="Waiting on others"
              items={data.waiting}
              empty={
                <div className="flex items-center gap-2 py-6 text-sm text-muted-foreground">
                  <Inbox className="size-4" aria-hidden /> Nothing of yours is waiting for approval.
                </div>
              }
            />
          )}
          {data.info.length > 0 && <Section title="Good to know" items={data.info} />}
        </div>
      )}
    </AppPage>
  )
}
