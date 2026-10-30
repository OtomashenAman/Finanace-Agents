import type { FlowUi } from "../types"
import { HOME_LABEL, PURPOSES } from "./meta"
import { BankStats } from "./stats"
import { BANK_STEPS, bankNextAction } from "./steps"
import { UnappliedCashPage } from "./unapplied-page"

export const bankRecon: FlowUi = {
  purposes: PURPOSES,
  steps: BANK_STEPS,
  nextAction: bankNextAction,
  showsCommitments: false,
  ownsPosting: true,
  home: { label: HOME_LABEL, Page: UnappliedCashPage },
  Stats: BankStats,
}
