import type { ReactNode } from "react"
import { Link, useLocation } from "react-router"

import { AppPage } from "@/components/layout/app-page"
import { cn } from "@/lib/utils"

import { useFinanceDashboard } from "../hooks"

const TABS = [
  { to: "/finance", label: "Dashboard" },
  { to: "/finance/cases", label: "Cases" },
  { to: "/finance/queue", label: "My Queue" },
  { to: "/finance/setup", label: "Setup" },
]

function FinanceTabs() {
  const { pathname } = useLocation()
  const queue = useFinanceDashboard().data?.my_queue.length ?? 0
  const active = (to: string) => (to === "/finance" ? pathname === "/finance" : pathname.startsWith(to))
  return (
    <nav aria-label="Finance POD" className="mb-4 flex gap-1 border-b border-border/60">
      {TABS.map((tab) => (
        <Link
          key={tab.to}
          to={tab.to}
          className={cn(
            "-mb-px flex items-center gap-1.5 border-b-2 px-4 py-2.5 text-sm font-medium transition-colors",
            active(tab.to) ? "border-primary text-primary" : "border-transparent text-muted-foreground hover:text-foreground",
          )}
        >
          {tab.label}
          {tab.to === "/finance/queue" && queue > 0 && (
            <span className="rounded-full bg-primary px-1.5 text-[10px] font-bold text-primary-foreground">{queue}</span>
          )}
        </Link>
      ))}
    </nav>
  )
}

/** A Finance POD page: the shared frame with the PODs' own look (`.pod-theme`) and tabs. */
export function FinancePage({ title, subtitle, children }: { title: string; subtitle?: string; children: ReactNode }) {
  return (
    <div className="pod-theme">
      <AppPage title={title} subtitle={subtitle}>
        <FinanceTabs />
        {children}
      </AppPage>
    </div>
  )
}
