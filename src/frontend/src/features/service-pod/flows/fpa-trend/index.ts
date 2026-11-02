import type { FlowUi } from "../types"
import { HOME_LABEL } from "./meta"
import { FpaPeriodsPage } from "./periods-page"
import { FpaStats } from "./stats"
import { FPA_STEPS, fpaNextAction } from "./steps"

export const fpaTrend: FlowUi = {
  purposes: {},
  steps: FPA_STEPS,
  nextAction: fpaNextAction,
  showsCommitments: false,
  ownsPosting: true,
  home: { label: HOME_LABEL, Page: FpaPeriodsPage },
  Stats: FpaStats,
}
