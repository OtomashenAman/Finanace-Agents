import type { FlowUi } from "../types"
import { HOME_LABEL } from "./meta"
import { TreasurySourcesPage } from "./sources-page"
import { TreasuryStats } from "./stats"
import { TREASURY_STEPS, treasuryNextAction } from "./steps"

export const treasury: FlowUi = {
  purposes: {},
  steps: TREASURY_STEPS,
  nextAction: treasuryNextAction,
  showsCommitments: false,
  ownsPosting: true,
  home: { label: HOME_LABEL, Page: TreasurySourcesPage },
  Stats: TreasuryStats,
}
