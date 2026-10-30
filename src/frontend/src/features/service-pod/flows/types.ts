import type { ComponentType } from "react"

import type { CaseDetail, Message } from "../api"

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
  /** Its workspace's first screen (/pod/<slug>); cases open from there. None: cases only */
  home?: { label: string; Page: ComponentType }
  /** Two or three live figures for its card on the Workflows page */
  Stats?: ComponentType
  /** How an imported reply is reviewed next to the raw email (default: the AI reading box) */
  ReplyPanel?: ComponentType<{ c: CaseDetail; m: Message }>
}
