import type { ReactNode } from "react"
import { Link, useLocation } from "react-router"
import { FlaskConical, LoaderCircle } from "lucide-react"

import { Alert } from "@/components/ui/alert"
import { Button, type ButtonProps } from "@/components/ui/button"
import { useCurrentUser } from "@/features/auth/hooks"
import { isAdmin } from "@/features/auth/roles"
import { cn } from "@/lib/utils"

import { useWorkflows } from "../hooks"
import { TONE_CLASSES } from "../labels"

interface Tab {
  to: string
  label: string
  /** who sees it: anyone working on cases, or only posters (Finance Admin) */
  for: "cases" | "posters" | "all"
}

const TABS: Tab[] = [
  { to: "/pod", label: "Workflows", for: "all" },
  { to: "/pod/inbox", label: "Inbox", for: "cases" },
  { to: "/pod/review", label: "AI Review", for: "cases" },
  { to: "/pod/tasks", label: "Manual QB Tasks", for: "posters" },
  { to: "/pod/sources", label: "Sources", for: "posters" },
]
const SHARED = TABS.slice(1).map((t) => t.to)

/** The same five tabs whatever the number of workflows (deck: one shared navigation);
 *  each workflow's own screens live in its workspace under Workflows. */
export function PodTabs() {
  const { pathname } = useLocation()
  const { data: user } = useCurrentUser()
  const { data: workflows = [] } = useWorkflows()
  const caps = workflows.flatMap((w) => w.my_capacities)
  const show = (tab: Tab) =>
    tab.for === "all" ||
    isAdmin(user) ||
    (tab.for === "posters" ? caps.includes("poster") : caps.some((c) => c !== "poster"))
  const active = (tab: Tab) =>
    tab.to === "/pod" ? !SHARED.some((to) => pathname.startsWith(to)) : pathname.startsWith(tab.to)
  return (
    <nav aria-label="Service POD" className="mb-6 flex gap-1 overflow-x-auto border-b">
      {TABS.filter(show).map((tab) => (
        <Link
          key={tab.to}
          to={tab.to}
          aria-current={active(tab) ? "page" : undefined}
          className={cn(
            "-mb-px shrink-0 border-b-2 px-4 py-2.5 text-sm font-medium transition-colors",
            active(tab) ? "border-primary text-primary" : "border-transparent text-muted-foreground hover:text-foreground",
          )}
        >
          {tab.label}
        </Link>
      ))}
    </nav>
  )
}

export function Pill({ label, tone }: { label: string; tone: keyof typeof TONE_CLASSES }) {
  return <span className={cn("rounded px-2 py-0.5 text-xs font-medium whitespace-nowrap", TONE_CLASSES[tone])}>{label}</span>
}

export function DemoBadge() {
  return (
    <span
      className="inline-flex items-center gap-1 rounded bg-amber-100 px-2 py-0.5 text-xs font-semibold text-amber-900"
      title="Fictional demonstration data, never the company's books"
    >
      <FlaskConical className="size-3" aria-hidden />
      DEMO DATA
    </span>
  )
}

export function Card({
  title,
  hint,
  actions,
  children,
  className,
}: {
  title: string
  hint?: ReactNode
  actions?: ReactNode
  children: ReactNode
  className?: string
}) {
  return (
    <section className={cn("rounded-lg border bg-card p-5", className)} aria-label={title}>
      <div className="mb-3 flex flex-wrap items-start justify-between gap-2 border-b pb-3">
        <div>
          <h2 className="text-base font-semibold text-brand-navy">{title}</h2>
          {hint && <p className="mt-0.5 text-xs text-muted-foreground">{hint}</p>}
        </div>
        {actions}
      </div>
      {children}
    </section>
  )
}

export function Loading({ what }: { what: string }) {
  return (
    <div className="flex justify-center py-12" role="status">
      <LoaderCircle className="size-6 animate-spin text-primary" aria-hidden />
      <span className="sr-only">Loading {what}…</span>
    </div>
  )
}

export function LoadError({ what }: { what: string }) {
  return <Alert>Couldn't load {what}. Refresh the page to try again.</Alert>
}

export function Empty({ children }: { children: ReactNode }) {
  return <p className="py-6 text-center text-sm text-muted-foreground">{children}</p>
}

/** A button for a server-guarded action: disabled with the server's reason as its tooltip. */
export function GuardedButton({
  reason,
  children,
  ...props
}: ButtonProps & { reason: string | null | undefined }) {
  const blocked = reason !== null && reason !== undefined
  return (
    <span title={blocked ? reason : undefined} className="inline-flex">
      <Button size="sm" disabled={blocked || props.disabled} {...props}>
        {children}
      </Button>
    </span>
  )
}

export function Field({ label, children, hint }: { label: string; children: ReactNode; hint?: string }) {
  return (
    <label className="block space-y-1 text-sm">
      <span className="font-medium text-brand-navy">{label}</span>
      {children}
      {hint && <span className="block text-xs text-muted-foreground">{hint}</span>}
    </label>
  )
}
