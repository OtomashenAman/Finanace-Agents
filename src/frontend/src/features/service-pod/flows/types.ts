import type { ComponentType } from "react"

import type { CaseDetail } from "../api"

/** What a workflow adds to the shared Service POD screens. */
export interface FlowUi {
  /** Message purposes it drafts (mirrors the backend's hooks), purpose -> label */
  purposes: Record<string, string>
  /** Its own panel at the top of a case */
  CasePanel: ComponentType<{ c: CaseDetail }>
  /** Shows the generic commitments card (promises to pay) */
  showsCommitments: boolean
  /** Queues postings itself instead of the generic "propose posting" form */
  ownsPosting: boolean
}
