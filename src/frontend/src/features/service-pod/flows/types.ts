import type { ComponentType } from "react"

import type { CaseDetail, Message } from "../api"

/** What a workflow adds to the shared Service POD screens. */
export interface FlowUi {
  /** Message purposes it drafts (mirrors the backend's hooks), purpose -> label */
  purposes: Record<string, string>
  /** Its own panel at the top of a case (when it has no steps) */
  CasePanel?: ComponentType<{ c: CaseDetail }>
  /** The case as the deck's screens: one step at a time, opened where work is waiting */
  steps?: FlowStep[]
  /** The one thing to do next on a case (and which step it's on) */
  nextAction?: (c: CaseDetail) => NextAction
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

export interface FlowStep {
  key: string
  label: string
  /** Something waiting on this step (shown as a count) */
  badge?: (c: CaseDetail) => number
  /** One line for the folded step on the case timeline (what happened there) */
  summary?: (c: CaseDetail) => string | null
  Body: ComponentType<{ c: CaseDetail }>
}

export interface NextAction {
  text: string
  /** the step it happens on */
  step?: string
  /** do: you can act; wait: the customer or a send is next; done: nothing left */
  kind: "do" | "wait" | "done"
  /** Where the case stands, in plain words for its status chip */
  phase: CasePhase
}

export type CasePhase = "compose" | "waiting" | "review" | "ready" | "posting" | "approved" | "completed" | "cancelled"
