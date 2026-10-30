import type { FlowUi } from "../types"
import { BankPanel } from "./case-panel"
import { HOME_LABEL } from "./meta"
import { BankStats } from "./stats"
import { UnappliedCashPage } from "./unapplied-page"

export const bankRecon: FlowUi = {
  purposes: {
    allocation_request: "Ask which invoices the payment covers",
    acknowledgement: "Confirm how the payment was applied",
  },
  CasePanel: BankPanel,
  showsCommitments: false,
  ownsPosting: true,
  home: { label: HOME_LABEL, Page: UnappliedCashPage },
  Stats: BankStats,
}
