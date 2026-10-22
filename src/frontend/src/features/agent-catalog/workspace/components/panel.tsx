import type { ReactNode } from "react"

import { cn } from "@/lib/utils"

interface PanelProps {
  title: ReactNode
  action?: ReactNode
  className?: string
  children: ReactNode
}

/** White card with a ruled title row, as used throughout the workspace screens. */
export function Panel({ title, action, className, children }: PanelProps) {
  return (
    <section className={cn("rounded-lg border bg-card p-5 sm:p-6", className)}>
      <div className="flex flex-wrap items-center justify-between gap-3 border-b pb-4">
        <h2 className="text-lg font-semibold text-brand-navy">{title}</h2>
        {action}
      </div>
      <div className="pt-5">{children}</div>
    </section>
  )
}
