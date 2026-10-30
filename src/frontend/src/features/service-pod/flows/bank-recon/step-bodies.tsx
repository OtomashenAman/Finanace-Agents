import type { CaseDetail } from "../../api"
import { Messages } from "../../components/case-messages"
import { ReviewTasks } from "../../components/case-sections"
import { BankAllocation, BankArLink, BankPosting, BankReceipt } from "./case-panel"
import { PURPOSES } from "./meta"

const REQUEST = "allocation_request"
const ACK = "acknowledgement"

export function ReceiptAndRequest({ c }: { c: CaseDetail }) {
  return (
    <>
      <BankReceipt c={c} />
      <Messages
        c={c}
        title="Ask the customer"
        hint="Which invoices, and how much of each, the payment covers. Checked and approved before it's sent."
        filter={(m) => m.direction === "outbound" && m.purpose !== ACK}
        importReplies={false}
        purposes={PURPOSES}
        defaultPurpose={REQUEST}
        empty="No email yet: suggest a draft below."
      />
    </>
  )
}

export function CustomerAllocation({ c }: { c: CaseDetail }) {
  return (
    <>
      <Messages
        c={c}
        title="Customer replies"
        hint="Import the reply; its allocation is read in the customer's own words."
        filter={(m) => m.direction === "inbound"}
        compose={false}
        empty="No reply imported yet."
      />
      <BankAllocation c={c} />
      <ReviewTasks c={c} />
    </>
  )
}

export function PostingAndVerify({ c }: { c: CaseDetail }) {
  return (
    <>
      <BankPosting c={c} />
      <BankArLink c={c} />
      <Messages
        c={c}
        title="Acknowledgement"
        hint="Confirm to the customer how the payment was applied: only once the posting is verified."
        filter={(m) => m.direction === "outbound" && m.purpose === ACK}
        importReplies={false}
        purposes={PURPOSES}
        defaultPurpose={ACK}
        empty="Nothing sent yet."
      />
    </>
  )
}
