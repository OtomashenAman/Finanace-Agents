import type { FlowUi } from "../types"
import { ArPanel } from "./case-panel"
import { HOME_LABEL } from "./meta"
import { ArPortfolioPage } from "./portfolio-page"
import { ArReplyReview } from "./reply-review"
import { ArStats } from "./stats"

export const arCollections: FlowUi = {
  purposes: {
    payment_schedule_request: "Ask for amounts and payment dates",
    follow_up: "Follow-up reply",
  },
  CasePanel: ArPanel,
  showsCommitments: true,
  ownsPosting: false,
  home: { label: HOME_LABEL, Page: ArPortfolioPage },
  Stats: ArStats,
  ReplyPanel: ArReplyReview,
}
