import type { ReactNode } from "react"

import { AppPage } from "@/components/layout/app-page"

/** A Service POD page: the shared frame with the POD's own look (`.pod-theme`) and a title
 *  that names the page (not "Service POD" everywhere). */
export function PodPage({ title, subtitle, children }: { title: string; subtitle?: string; children: ReactNode }) {
  return (
    <div className="pod-theme">
      <AppPage title={title} subtitle={subtitle}>
        {children}
      </AppPage>
    </div>
  )
}
