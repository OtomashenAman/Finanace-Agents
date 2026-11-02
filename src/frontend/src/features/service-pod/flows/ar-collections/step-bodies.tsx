import type { CaseDetail } from "../../api"
import { Messages } from "../../components/case-messages"
import { Commitments, ReviewTasks } from "../../components/case-sections"
import { ArFollowThrough, ArHandover, ArInvoices } from "./case-panel"
import { PURPOSES } from "./meta"
import { ArReplyReview } from "./reply-review"

const REQUEST = "payment_schedule_request"
const FOLLOW_UP = "follow_up"

export function InvoicesAndEmail({ c }: { c: CaseDetail }) {
  return (
    <>
      <ArInvoices c={c} />
      <Messages
        c={c}
        title="Email to the customer"
        hint="The invoice figures come from the source and stay locked; the email is checked and approved before it's sent."
        filter={(m) => m.direction === "outbound" && m.purpose !== FOLLOW_UP}
        importReplies={false}
        purposes={PURPOSES}
        defaultPurpose={REQUEST}
        empty="No email yet: suggest a draft below."
      />
    </>
  )
}

export function CustomerReply({ c }: { c: CaseDetail }) {
  return (
    <>
      <Messages
        c={c}
        title="Customer replies"
        hint="Replies come in from the mailbox; the AI reads each one next to our email, and anything unclear becomes a review task."
        filter={(m) => m.direction === "inbound"}
        compose={false}
        ReplyPanel={ArReplyReview}
        empty="No reply imported yet."
      />
      <ReviewTasks c={c} />
    </>
  )
}

export function ScheduleAndClose({ c }: { c: CaseDetail }) {
  return (
    <>
      <Commitments c={c} />
      <ArFollowThrough c={c} />
      <ArHandover c={c} />
      <Messages
        c={c}
        title="Follow-up reply"
        hint="e.g. documents attached, or asking for a missing date."
        filter={(m) => m.direction === "outbound" && m.purpose === FOLLOW_UP}
        importReplies={false}
        purposes={PURPOSES}
        defaultPurpose={FOLLOW_UP}
        empty="No follow-up yet."
      />
    </>
  )
}
