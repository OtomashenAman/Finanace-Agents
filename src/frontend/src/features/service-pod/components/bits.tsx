import type { ReactNode } from "react"
import { Link, useLocation } from "react-router"
import { FlaskConical, LoaderCircle, Sparkles } from "lucide-react"

import { Alert } from "@/components/ui/alert"
import { Button, type ButtonProps } from "@/components/ui/button"
import { cn } from "@/lib/utils"

import type { WorkflowKey } from "../api"
import { useMyQueue } from "../hooks"
import { AI_AGENTS, TONE_CLASSES, type Tone } from "../labels"

const TABS = [
  { to: "/pod", label: "Dashboard" },
  { to: "/pod/cases", label: "Cases" },
  { to: "/pod/queue", label: "My Queue" },
  { to: "/pod/sources", label: "Sources" },
]
const SHARED = TABS.slice(1).map((t) => t.to)

/** Live pulsing status dot for AI telemetry */
export function LivePulse({
  color = "emerald",
  label,
  className,
}: {
  color?: "emerald" | "violet" | "amber" | "sky"
  label?: string
  className?: string
}) {
  const colorMap = {
    emerald: "bg-emerald-500",
    violet: "bg-violet-500",
    amber: "bg-amber-500",
    sky: "bg-sky-500",
  }
  return (
    <span className={cn("inline-flex items-center gap-1.5 text-xs font-medium", className)}>
      <span className="relative flex size-2">
        <span className={cn("absolute inline-flex h-full w-full animate-ping rounded-full opacity-75", colorMap[color])} />
        <span className={cn("relative inline-flex size-2 rounded-full", colorMap[color])} />
      </span>
      {label && <span>{label}</span>}
    </span>
  )
}

/** The same four tabs whatever the number of workflows; includes active AI telemetry pulse */
export function PodTabs() {
  const { pathname } = useLocation()
  const { count } = useMyQueue()
  const active = (tab: (typeof TABS)[number]) =>
    tab.to === "/pod" ? !SHARED.some((to) => pathname.startsWith(to)) : pathname.startsWith(tab.to)
  return (
    <div className="mb-4 flex flex-wrap items-center justify-between gap-3 border-b border-border/60">
      <nav aria-label="Service POD" className="flex flex-wrap sm:flex-nowrap gap-1">
        {TABS.map((tab) => (
          <Link
            key={tab.to}
            to={tab.to}
            aria-current={active(tab) ? "page" : undefined}
            className={cn(
              "-mb-px shrink-0 border-b-2 px-3.5 py-2 text-xs sm:text-sm font-medium transition-colors",
              active(tab) ? "border-primary text-primary font-semibold" : "border-transparent text-muted-foreground hover:text-foreground",
            )}
          >
            {tab.label}
            {tab.to === "/pod/queue" && count > 0 && (
              <span className="ml-1.5 rounded-full bg-amber-100 px-1.5 py-0.2 text-[10px] font-bold text-amber-900 shadow-2xs dark:bg-amber-950 dark:text-amber-200">
                {count}
              </span>
            )}
          </Link>
        ))}
      </nav>
      <div className="hidden sm:flex items-center gap-2 pb-1.5 text-xs text-muted-foreground">
        <LivePulse color="emerald" label="5 AI Agents Active" className="text-emerald-700 font-semibold dark:text-emerald-300" />
      </div>
    </div>
  )
}

export function Pill({ label, tone }: { label: string; tone: Tone }) {
  return <span className={cn("inline-flex items-center rounded-md px-2 py-0.5 text-[11px] font-medium whitespace-nowrap shadow-2xs", TONE_CLASSES[tone])}>{label}</span>
}

/** Visual badge for AI suggestions / actions with sparkles */
export function AiBadge({
  label = "AI Suggestion",
  confidence,
  className,
}: {
  label?: string
  confidence?: string | number
  className?: string
}) {
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1 rounded-md border border-violet-200/90 bg-gradient-to-r from-violet-50 to-indigo-50/80 px-2 py-0.5 text-[11px] font-semibold text-violet-800 shadow-2xs dark:border-violet-800/60 dark:from-violet-950/60 dark:to-indigo-950/40 dark:text-violet-300",
        className,
      )}
    >
      <Sparkles className="size-3 text-violet-600 dark:text-violet-400" aria-hidden />
      <span>{label}</span>
      {confidence !== undefined && (
        <span className="ml-0.5 rounded bg-violet-200/60 px-1 py-0.2 text-[10px] font-bold text-violet-900 dark:bg-violet-800/60 dark:text-violet-200">
          {typeof confidence === "number" ? `${Math.round(confidence * 100)}%` : confidence}
        </span>
      )}
    </span>
  )
}

/** Visual chip showing specific AI agent metadata */
export function AgentBadge({
  workflow,
  showRole = false,
  className,
}: {
  workflow: WorkflowKey
  showRole?: boolean
  className?: string
}) {
  const agent = AI_AGENTS[workflow]
  if (!agent) return null
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1.5 rounded-md border px-2 py-0.5 text-xs font-medium shadow-2xs",
        agent.toneColor,
        className,
      )}
      title={`${agent.name} (${agent.role}): ${agent.description}`}
    >
      <span className="text-xs leading-none">{agent.avatar}</span>
      <span className="font-semibold">{agent.name}</span>
      {showRole && <span className="text-[10px] opacity-75">· {agent.role}</span>}
    </span>
  )
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

/** AI-accented card with subtle glowing border */
export function AiCard({
  title,
  hint,
  badge,
  actions,
  children,
  className,
}: {
  title: string
  hint?: ReactNode
  badge?: ReactNode
  actions?: ReactNode
  children: ReactNode
  className?: string
}) {
  return (
    <section
      className={cn(
        "relative overflow-hidden rounded-xl border border-ai-border bg-gradient-to-b from-card to-ai-soft/60 p-4 pl-5 shadow-[0_1px_2px_rgb(76_47_184/0.05),0_10px_28px_-14px_rgb(76_47_184/0.25)] before:absolute before:inset-y-0 before:left-0 before:w-1 before:bg-gradient-to-b before:from-ai before:to-indigo-400 dark:border-violet-900/50 dark:to-violet-950/10",
        className,
      )}
      aria-label={title}
    >
      <div className="mb-3 flex flex-wrap items-start justify-between gap-2 border-b border-border/60 pb-2.5">
        <div>
          <div className="flex items-center gap-2">
            <h2 className="text-sm font-semibold tracking-tight text-foreground">{title}</h2>
            {badge ?? <AiBadge label="Autonomous" />}
          </div>
          {hint && <p className="mt-0.5 text-xs text-muted-foreground leading-normal">{hint}</p>}
        </div>
        {actions}
      </div>
      {children}
    </section>
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
    <section
      className={cn(
        "rounded-xl border border-border/80 bg-card p-4 shadow-[0_1px_3px_rgba(15,33,66,0.04),0_8px_24px_-12px_rgba(15,33,66,0.08)] transition-shadow duration-200",
        className,
      )}
      aria-label={title}
    >
      <div className="mb-3 flex flex-wrap items-start justify-between gap-2 border-b border-border/70 pb-2.5">
        <div>
          <h2 className="text-sm font-bold tracking-tight text-brand-navy dark:text-foreground">{title}</h2>
          {hint && <p className="mt-0.5 max-w-3xl text-xs leading-normal text-muted-foreground">{hint}</p>}
        </div>
        {actions}
      </div>
      {children}
    </section>
  )
}

export function Loading({ what }: { what: string }) {
  return (
    <div className="flex flex-col items-center justify-center py-12 gap-2 text-xs text-muted-foreground" role="status">
      <LoaderCircle className="size-6 animate-spin text-primary" aria-hidden />
      <span>Loading {what}…</span>
    </div>
  )
}

export function LoadError({ what }: { what: string }) {
  return <Alert>Couldn't load {what}. Refresh the page to try again.</Alert>
}

export function Empty({ children, icon }: { children: ReactNode; icon?: ReactNode }) {
  return (
    <div className="flex flex-col items-center justify-center rounded-lg border border-dashed border-border/80 bg-muted/20 py-8 px-4 text-center">
      <div className="flex size-10 items-center justify-center rounded-full bg-muted/60 text-muted-foreground mb-2 shadow-2xs">
        {icon ?? <Sparkles className="size-5 text-violet-500/70" />}
      </div>
      <p className="text-sm font-medium text-muted-foreground max-w-sm">{children}</p>
    </div>
  )
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
