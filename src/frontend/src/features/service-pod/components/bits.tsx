import type { ReactNode } from "react"
import { Link, useLocation } from "react-router"
import { FlaskConical, LoaderCircle } from "lucide-react"

import { Alert } from "@/components/ui/alert"
import { Button, type ButtonProps } from "@/components/ui/button"
import { cn } from "@/lib/utils"

import { useMyQueue } from "../hooks"
import { TONE_CLASSES } from "../labels"

const TABS = [
  { to: "/pod", label: "Dashboard" },
  { to: "/pod/cases", label: "Cases" },
  { to: "/pod/queue", label: "My Queue" },
  { to: "/pod/sources", label: "Sources" },
]
const SHARED = TABS.slice(1).map((t) => t.to)

/** The same four tabs whatever the number of workflows; each workflow's own screen (e.g. the
 *  AR portfolio, where cases start) opens from Home. */
export function PodTabs() {
  const { pathname } = useLocation()
  const { count } = useMyQueue()
  const active = (tab: (typeof TABS)[number]) =>
    tab.to === "/pod" ? !SHARED.some((to) => pathname.startsWith(to)) : pathname.startsWith(tab.to)
  return (
    <nav aria-label="Service POD" className="mb-4 flex gap-1 overflow-x-auto border-b border-border/60">
      {TABS.map((tab) => (
        <Link
          key={tab.to}
          to={tab.to}
          aria-current={active(tab) ? "page" : undefined}
          className={cn(
            "-mb-px shrink-0 border-b-2 px-3.5 py-2 text-xs sm:text-sm font-medium transition-colors",
            active(tab) ? "border-primary text-primary" : "border-transparent text-muted-foreground hover:text-foreground",
          )}
        >
          {tab.label}
          {tab.to === "/pod/queue" && count > 0 && (
            <span className="ml-1.5 rounded-full bg-amber-100 px-1.5 py-0.2 text-[10px] font-semibold text-amber-900 dark:bg-amber-950 dark:text-amber-200">{count}</span>
          )}
        </Link>
      ))}
    </nav>
  )
}

export function Pill({ label, tone }: { label: string; tone: keyof typeof TONE_CLASSES }) {
  return <span className={cn("inline-flex items-center rounded-md px-2 py-0.5 text-[11px] font-medium whitespace-nowrap shadow-2xs", TONE_CLASSES[tone])}>{label}</span>
}

export function DemoBadge() {
  return (
    <span
      className="inline-flex items-center gap-1 rounded-md border border-amber-300/80 bg-amber-50 px-2 py-0.5 text-[11px] font-semibold text-amber-900 dark:border-amber-900/50 dark:bg-amber-950/40 dark:text-amber-300"
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
    <section className={cn("rounded-lg border border-border/70 bg-card p-4 shadow-2xs", className)} aria-label={title}>
      <div className="mb-2.5 flex flex-wrap items-start justify-between gap-2 border-b border-border/60 pb-2.5">
        <div>
          <h2 className="text-sm font-semibold tracking-tight text-foreground">{title}</h2>
          {hint && <p className="mt-0.5 text-xs text-muted-foreground leading-normal">{hint}</p>}
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
