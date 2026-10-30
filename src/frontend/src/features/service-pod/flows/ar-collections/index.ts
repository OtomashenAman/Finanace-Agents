import type { FlowUi } from "../types"
import { HOME_LABEL, PURPOSES } from "./meta"
import { ArPortfolioPage } from "./portfolio-page"
import { ArReplyReview } from "./reply-review"
import { ArStats } from "./stats"
import { AR_STEPS, arNextAction } from "./steps"

export const arCollections: FlowUi = {
  purposes: PURPOSES,
  steps: AR_STEPS,
  nextAction: arNextAction,
  showsCommitments: true,
  ownsPosting: false,
  home: { label: HOME_LABEL, Page: ArPortfolioPage },
  Stats: ArStats,
  ReplyPanel: ArReplyReview,
}
