import type { ReactNode } from "react"

import { PodPage } from "@/features/service-pod/components/pod-page"

/** A Finance POD page: the POD look and the page's content. Its navigation lives in the
 *  Finance POD's own sidebar (FpodShell). */
export function FpodPage({ title, subtitle, children }: { title: string; subtitle?: string; children: ReactNode }) {
  return (
    <PodPage title={title} subtitle={subtitle}>
      {children}
    </PodPage>
  )
}
