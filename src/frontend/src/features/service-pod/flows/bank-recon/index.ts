import type { FlowUi } from "../types"
import { BankPanel } from "./case-panel"

export const bankRecon: FlowUi = {
  purposes: {
    allocation_request: "Ask which invoices the payment covers",
    acknowledgement: "Confirm how the payment was applied",
  },
  CasePanel: BankPanel,
  showsCommitments: false,
  ownsPosting: true,
}
