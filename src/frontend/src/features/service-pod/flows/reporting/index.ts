import type { FlowUi } from "../types"
import { HOME_LABEL } from "./meta"
import { ReportMonthsPage } from "./months-page"
import { ReportingStats } from "./stats"
import { REPORTING_STEPS, reportingNextAction } from "./steps"

export const reporting: FlowUi = {
  purposes: { pack_distribution: "Send the management pack" },
  steps: REPORTING_STEPS,
  nextAction: reportingNextAction,
  showsCommitments: false,
  ownsPosting: true,
  home: { label: HOME_LABEL, Page: ReportMonthsPage },
  Stats: ReportingStats,
}
