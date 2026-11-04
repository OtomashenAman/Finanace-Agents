import type { Tone } from "@/features/service-pod/labels"

import type { PriceStatus, RequestFileKind, RequestStatus } from "./api"
import type { ApplicationStatus } from "./clients-api"
import type { ExceptionStatus, InvoiceStatus } from "./invoices-api"
import type { OnboardingStatus, PoStatus } from "./procurement-api"

export const REQUEST_STATUS: Record<RequestStatus, [string, Tone]> = {
  draft: ["Draft", "neutral"],
  submitted: ["Awaiting approval", "info"],
  queried: ["Queried: back to requester", "warn"],
  approved: ["Approved: sourcing", "good"],
  ordered: ["PO issued", "good"],
  rejected: ["Rejected", "bad"],
  cancelled: ["Cancelled", "neutral"],
}

export const PRICE_STATUS: Record<PriceStatus, [string, Tone]> = {
  matches: ["At contract price", "good"],
  above_contract: ["Above contract price", "warn"],
  below_contract: ["Below contract price", "info"],
  no_estimate: ["Contract price known", "info"],
  no_match: ["Not in catalogue", "neutral"],
}

export const PO_STATUS: Record<PoStatus, [string, Tone]> = {
  draft: ["Draft: buyer checks", "neutral"],
  pending_approval: ["Waiting for approval", "warn"],
  approved: ["Approved: ready to issue", "info"],
  issued: ["Issued: waiting for acknowledgement", "info"],
  acknowledged: ["Acknowledged", "good"],
  cancelled: ["Cancelled", "neutral"],
}

export const ONBOARDING_STATUS: Record<OnboardingStatus, [string, Tone]> = {
  invited: ["Portal link sent", "info"],
  submitted: ["AP analyst to verify", "warn"],
  verified: ["Second approver to activate", "warn"],
  active: ["Active", "good"],
  rejected: ["Rejected", "bad"],
}

export const FILE_KIND: Record<RequestFileKind, string> = {
  quote: "Quote",
  specification: "Specification",
  other: "Other",
}

export type StepActor = "person" | "agent"

export interface ProcessStep {
  id: string // L3 number, e.g. "1.1"
  title: string
  who: string
  tasks: { id: string; actor: StepActor; title: string; steps: string[] }[]
  live: boolean // built in the Finance POD yet
}

/** GIA AP Phase 1 (to-be): purchase request to purchase order. */
export const PHASE_1: ProcessStep[] = [
  {
    id: "1.1",
    title: "Capture the request",
    who: "Requester + request agent",
    live: true,
    tasks: [
      {
        id: "1.1.1",
        actor: "person",
        title: "Describe the need",
        steps: ["Item, quantity, purpose in form or chat", "Upload quote if available"],
      },
      {
        id: "1.1.2",
        actor: "agent",
        title: "Request agent enriches",
        steps: [
          "Suggests cost centre, lab, grant",
          "Checks catalogue and contract prices",
          "Flags missing data before submit",
        ],
      },
    ],
  },
  {
    id: "1.2",
    title: "Budget check and approval",
    who: "Budget agent + budget owner",
    live: true,
    tasks: [
      {
        id: "1.2.1",
        actor: "agent",
        title: "Budget agent checks",
        steps: ["Remaining budget or grant balance", "Grant allowability rules", "Routes by authority matrix"],
      },
      {
        id: "1.2.2",
        actor: "person",
        title: "Budget owner decides",
        steps: ["Sees budget impact on screen", "Approves, rejects or queries"],
      },
    ],
  },
  {
    id: "1.3",
    title: "Select vendor",
    who: "Sourcing agent + buyer",
    live: true,
    tasks: [
      {
        id: "1.3.1",
        actor: "agent",
        title: "Sourcing agent",
        steps: [
          "Finds approved vendors and contracts",
          "Requests quotes above threshold",
          "Compares quotes side by side",
        ],
      },
      { id: "1.3.2", actor: "person", title: "Buyer chooses", steps: ["Reviews comparison", "Confirms vendor and terms"] },
    ],
  },
  {
    id: "1.5",
    title: "Onboard new vendor",
    who: "Onboarding agent + AP analyst",
    live: true,
    tasks: [
      {
        id: "1.5.1",
        actor: "agent",
        title: "Onboarding agent",
        steps: ["Sends secure portal link", "Reads tax form and bank letter", "Validates tax ID; sanctions screen"],
      },
      {
        id: "1.5.2",
        actor: "person",
        title: "AP analyst verifies",
        steps: ["Calls back to confirm bank", "Second approver activates vendor"],
      },
    ],
  },
  {
    id: "1.6",
    title: "Create and issue PO",
    who: "PO agent + buyer",
    live: true,
    tasks: [
      {
        id: "1.6.1",
        actor: "agent",
        title: "PO agent",
        steps: ["Drafts PO from approved request", "Applies coding and terms", "Sends PO; logs acknowledgement"],
      },
      { id: "1.6.2", actor: "person", title: "Buyer approves", steps: ["Approves POs above limit"] },
    ],
  },
]

export const GUARDRAILS = [
  "No PO without an approved request",
  "Bank changes are never accepted by email",
  "Nobody approves a request they raised",
  "Quotes required at or above the purchasing threshold",
  "New vendors need two-person approval",
]

export function money(value: string | number | null | undefined, currency?: string | null): string {
  if (value === null || value === undefined || value === "") return "—"
  const n = Number(value).toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })
  return currency ? `${currency} ${n}` : n
}

export function formatDate(value: string | null | undefined): string {
  return value ? new Date(`${value}T00:00:00`).toLocaleDateString(undefined, { dateStyle: "medium" }) : "—"
}

// --- AP Phase 3: invoice processing & matching ---------------------------------------------

export const INVOICE_STATUS: Record<InvoiceStatus, [string, Tone]> = {
  captured: ["Captured: AP confirms", "neutral"],
  duplicate: ["Blocked: possible duplicate", "bad"],
  posted: ["Posted: matching", "info"],
  exception: ["Exception", "warn"],
  ready: ["Matched: ready to pay", "good"],
  paid: ["Paid", "good"],
  rejected: ["Rejected", "neutral"],
}

export const EXCEPTION_STATUS: Record<ExceptionStatus, [string, Tone]> = {
  open: ["Buyer decides", "warn"],
  waiting_vendor: ["Waiting for credit note", "info"],
  waiting_receipt: ["Waiting for receiver", "info"],
  resolved: ["Resolved", "good"],
}

export const ISSUE_KIND: Record<string, string> = {
  price: "Price variance",
  quantity: "Quantity variance",
  no_receipt: "No receipt",
  not_on_po: "Not on the PO",
  no_po: "No PO",
  vendor: "Wrong vendor",
  header: "Totals don't add up",
}

export const LINE_STATUS: Record<string, [string, Tone]> = {
  match: ["Match", "good"],
  price_variance: ["Price variance", "warn"],
  quantity_variance: ["Quantity variance", "warn"],
  no_receipt: ["Not received", "warn"],
  not_on_po: ["Not on PO", "bad"],
}

/** GIA AP Phase 3 (to-be): invoice processing and matching. */
export const PHASE_3: ProcessStep[] = [
  {
    id: "3.2",
    title: "Post the invoice",
    who: "Posting agent",
    live: true,
    tasks: [
      { id: "3.2.1", actor: "agent", title: "Create invoice in ERP", steps: ["From validated data", "Attach source document"] },
      { id: "3.2.2", actor: "agent", title: "Duplicate guard", steps: ["Fuzzy match on number, amount", "Blocks and explains"] },
    ],
  },
  {
    id: "3.4",
    title: "Match",
    who: "Match agent",
    live: true,
    tasks: [
      { id: "3.4.1", actor: "agent", title: "Three-way match", steps: ["Line by line vs PO and receipt", "Applies GIA tolerances"] },
      { id: "3.4.2", actor: "agent", title: "Classify outcome", steps: ["Match: send to coding", "Variance: open exception"] },
    ],
  },
  {
    id: "3.5",
    title: "Resolve variances",
    who: "Exception agent + buyer",
    live: true,
    tasks: [
      { id: "3.5.1", actor: "agent", title: "Prepare the case", steps: ["Shows PO, receipt, invoice", "Drafts vendor query"] },
      { id: "3.5.2", actor: "person", title: "Buyer decides", steps: ["Accept, credit or amend PO"] },
      { id: "3.5.3", actor: "agent", title: "Close the loop", steps: ["Re-matches; releases invoice"] },
    ],
  },
  {
    id: "3.6",
    title: "Chase missing receipts",
    who: "Receipt agent + receiver",
    live: true,
    tasks: [
      { id: "3.6.1", actor: "agent", title: "Nudge receiver", steps: ["Requests confirmation"] },
      { id: "3.6.2", actor: "person", title: "Receiver confirms", steps: ["Posts receipt on mobile"] },
    ],
  },
]

export const PHASE_3_GUARDRAILS = [
  "Agents never change PO prices: only the buyer's amendment, recorded old and new",
  "Duplicates blocked by number, vendor, amount and date, with the reason shown",
  "A variance can't be accepted for goods nobody confirmed received",
  "All decisions logged",
]

// --- payments and vendor support -----------------------------------------------------------

/** Payments (to-be): proposed run, risk checks, release, post and support vendors. */
export const PAYMENTS_FLOW: ProcessStep[] = [
  {
    id: "pay-propose",
    title: "Propose payment run",
    who: "Payment agent + AP analyst",
    live: true,
    tasks: [
      { id: "pay-select", actor: "agent", title: "Select", steps: ["Approved, due, discount-eligible", "Groups by currency and bank"] },
      { id: "pay-risk", actor: "agent", title: "Risk checks", steps: ["Bank-change history", "Unusual amount or vendor"] },
      { id: "pay-callback", actor: "person", title: "AP analyst", steps: ["Call-back on flagged bank changes"] },
    ],
  },
  {
    id: "pay-release",
    title: "Release",
    who: "Treasury",
    live: true,
    tasks: [
      { id: "pay-review", actor: "person", title: "Review run", steps: ["Sees risk flags and totals"] },
      { id: "pay-dual", actor: "person", title: "Release", steps: ["Two different people approve"] },
    ],
  },
  {
    id: "pay-post",
    title: "Post and support vendors",
    who: "Vendor agent + AP analyst",
    live: true,
    tasks: [
      { id: "pay-remit", actor: "agent", title: "Post and remit", steps: ["Marks paid; sends remittance"] },
      { id: "pay-answer", actor: "agent", title: "Answer queries", steps: ["Status from the records in minutes", "Self-service help page"] },
      { id: "pay-analyst", actor: "person", title: "Analyst", steps: ["Disputes and escalations"] },
    ],
  },
]

export const PAYMENTS_GUARDRAILS = [
  "Agents cannot release payments: two different people do",
  "Bank changes never auto-accepted: call-back before paying",
  "Vendor answers go only to the email we hold for the vendor",
  "All decisions logged",
]

export const RUN_STATUS: Record<string, [string, Tone]> = {
  proposed: ["Proposed: review and release", "info"],
  partly_approved: ["One of two releases given", "warn"],
  released: ["Released: paid", "good"],
  cancelled: ["Cancelled", "neutral"],
}

export const QUERY_STATUS: Record<string, [string, Tone]> = {
  answered: ["Answered by the agent", "good"],
  escalated: ["With an analyst", "warn"],
  resolved: ["Answered by an analyst", "good"],
}

// --- receivables: client account and credit set-up (AR Phase 1) ---------------------------

export const APPLICATION_STATUS: Record<ApplicationStatus, [string, Tone]> = {
  invited: ["Link sent: waiting for the client", "info"],
  needs_info: ["Back with the client: gaps", "warn"],
  submitted: ["Client services to check", "warn"],
  proposed: ["Credit controller decides", "warn"],
  active: ["Account open", "good"],
  rejected: ["Rejected", "bad"],
}

export const RISK: Record<string, [string, Tone]> = {
  low: ["Low risk", "good"],
  medium: ["Medium risk", "warn"],
  high: ["High risk", "bad"],
}

export const REVIEW_STATUS: Record<string, [string, Tone]> = {
  proposed: ["Credit controller decides", "warn"],
  approved: ["Approved", "good"],
  dismissed: ["Dismissed", "neutral"],
}

export const DOC_KIND: Record<string, string> = {
  registration: "Business registration",
  tax: "Tax document",
  credit_report: "Credit report",
  trade_reference: "Trade reference",
  other: "Other",
}

/** A client's terms, in words: "USD 40,000.00 on Net 30" or "deposit only (50%)". */
export function termsText(t: { credit_limit: string | null; deposit_pct: string; payment_terms: string }, currency?: string | null): string {
  const deposit = Number(t.deposit_pct)
  if (t.credit_limit === null) return `Deposit only (${deposit}% up front) · ${t.payment_terms}`
  return `${money(t.credit_limit, currency)} on ${t.payment_terms}${deposit ? ` · ${deposit}% deposit` : ""}`
}

/** GIA AR Phase 1 (to-be): client account and credit set-up. */
export const RECEIVABLES_FLOW: ProcessStep[] = [
  {
    id: "1.1",
    title: "Client onboarding",
    who: "Onboarding agent + client",
    live: true,
    tasks: [
      { id: "1.1.1", actor: "person", title: "Client applies", steps: ["Completes portal form", "Uploads documents"] },
      {
        id: "1.1.2",
        actor: "agent",
        title: "Onboarding agent",
        steps: ["Reads and validates documents", "Runs compliance screening", "Flags gaps to client"],
      },
    ],
  },
  {
    id: "1.2",
    title: "Credit decision",
    who: "Credit agent + credit controller",
    live: true,
    tasks: [
      { id: "1.2.1", actor: "agent", title: "Credit agent", steps: ["Scores risk from data", "Proposes limit or deposit"] },
      { id: "1.2.2", actor: "person", title: "Credit controller", steps: ["Approves terms and limit"] },
    ],
  },
  {
    id: "1.3",
    title: "Create account",
    who: "Account agent",
    live: true,
    tasks: [
      { id: "1.3.1", actor: "agent", title: "Set up once", steps: ["Creates client in both systems", "Keeps them in sync"] },
      { id: "1.3.2", actor: "agent", title: "Monitor", steps: ["Reviews limits as history builds"] },
    ],
  },
]

export const RECEIVABLES_GUARDRAILS = [
  "No credit without human approval: the credit controller decides",
  "Whoever opened an application can't approve its credit",
  "Set up once from the approved record: ERP and lab system kept in sync",
  "All decisions logged",
]

export const QUERY_INTENT: Record<string, string> = {
  status: "Payment status",
  missing_invoice: "Missing invoice",
  dispute: "Dispute",
  other: "Other",
}
