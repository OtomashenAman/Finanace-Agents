import type { FlowUi } from "../types"
import { ArPanel } from "./case-panel"

export const arCollections: FlowUi = {
  purposes: {
    payment_schedule_request: "Ask for amounts and payment dates",
    follow_up: "Follow-up reply",
  },
  CasePanel: ArPanel,
  showsCommitments: true,
  ownsPosting: false,
}
