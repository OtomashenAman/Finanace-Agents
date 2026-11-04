import {
  Activity,
  Banknote,
  FileCheck,
  Landmark,
  Network,
  Users,
  Bot,
  Building2,
  ClipboardCheck,
  FileSearch,
  FileText,
  Gauge,
  HandCoins,
  Headset,
  MessageSquareWarning,
  PackageCheck,
  PiggyBank,
  ReceiptText,
  Scale,
  Search,
  Settings,
  ShieldCheck,
  ShoppingCart,
  Truck,
  UserCheck,
  type LucideIcon,
} from "lucide-react"

import type { Overview } from "./api"

/** One place that knows every area and agent of the Finance POD. Navigation, the overview
 *  and the agent directory are built from it: a new agent is one more entry here. */

export type AreaKey = "purchasing" | "invoices" | "payments" | "receivables"

export interface Page {
  to: string
  label: string
  icon: LucideIcon
  end?: boolean
  count?: (o: Overview) => number // a badge: items waiting there
}

export interface Area {
  key: AreaKey
  name: string
  tagline: string
  icon: LucideIcon
  pages: Page[]
}

export interface Agent {
  key: string
  name: string
  area: AreaKey
  icon: LucideIcon
  does: string
  people: string // who it works with
  to: string // where its work shows
  busy?: (o: Overview) => number // items it is waiting on people for
}

const sum = (rec: Partial<Record<string, number>> | undefined, keys: string[]) =>
  keys.reduce((n, k) => n + (rec?.[k] ?? 0), 0)

export const AREAS: Area[] = [
  {
    key: "purchasing",
    name: "Purchasing",
    tagline: "From a request to an issued purchase order",
    icon: ShoppingCart,
    pages: [
      { to: "/finance-pod/requests", label: "Requests", icon: ClipboardCheck },
      { to: "/finance-pod/approvals", label: "Approvals", icon: UserCheck, end: true, count: (o) => o.waiting_for_me },
      { to: "/finance-pod/vendors", label: "Vendors", icon: Building2, count: (o) => o.onboarding_open },
      { to: "/finance-pod/orders", label: "Purchase orders", icon: Truck, end: true, count: (o) => o.pos_waiting_for_me },
    ],
  },
  {
    key: "invoices",
    name: "Invoices",
    tagline: "Capture, duplicate guard and three-way match",
    icon: ReceiptText,
    pages: [
      { to: "/finance-pod/invoices", label: "Invoices", icon: FileText, count: (o) => o.invoices.captured ?? 0 },
      {
        to: "/finance-pod/exceptions",
        label: "Exceptions",
        icon: Scale,
        end: true,
        count: (o) => sum(o.exceptions_open, ["open", "waiting_vendor", "waiting_receipt"]),
      },
    ],
  },
  {
    key: "payments",
    name: "Payments",
    tagline: "Payment runs, remittances and vendor questions",
    icon: Banknote,
    pages: [
      { to: "/finance-pod/payments", label: "Payment runs", icon: HandCoins, count: (o) => sum(o.payment_runs, ["proposed", "partly_approved"]) },
      { to: "/finance-pod/vendor-queries", label: "Vendor queries", icon: Headset, end: true, count: (o) => o.queries.escalated ?? 0 },
    ],
  },
  {
    key: "receivables",
    name: "Receivables",
    tagline: "Client accounts and credit: set up once, reviewed as history builds",
    icon: Landmark,
    pages: [
      { to: "/finance-pod/clients", label: "Client accounts", icon: Users, count: (o) => sum(o.client_applications, ["submitted", "proposed"]) },
      { to: "/finance-pod/credit-reviews", label: "Credit reviews", icon: Activity, end: true, count: (o) => o.credit_reviews_open },
    ],
  },
]

export const GENERAL: Page[] = [
  { to: "/finance-pod/measures", label: "Measures", icon: Gauge, end: true },
  { to: "/finance-pod/setup", label: "Setup", icon: Settings, end: true },
]

export const AGENTS: Agent[] = [
  { key: "request", name: "Request agent", area: "purchasing", icon: Bot, to: "/finance-pod/requests",
    does: "Turns a described need into a request, suggests the coding, checks contract prices and flags what's missing.",
    people: "Requester", busy: (o) => o.requests.draft ?? 0 },
  { key: "budget", name: "Budget agent", area: "purchasing", icon: PiggyBank, to: "/finance-pod/approvals",
    does: "Checks the budget or grant balance and the grant's rules, and routes the request by the authority matrix.",
    people: "Budget owner", busy: (o) => o.requests.submitted ?? 0 },
  { key: "sourcing", name: "Sourcing agent", area: "purchasing", icon: Search, to: "/finance-pod/requests?status=approved",
    does: "Finds approved vendors and contracts, requests quotes above the threshold and compares them side by side.",
    people: "Buyer", busy: (o) => o.requests.approved ?? 0 },
  { key: "onboarding", name: "Onboarding agent", area: "purchasing", icon: ShieldCheck, to: "/finance-pod/vendors",
    does: "Sends the secure portal link, reads the tax form and bank letter, validates the tax ID and screens sanctions.",
    people: "AP analyst · second approver", busy: (o) => o.onboarding_open },
  { key: "po", name: "PO agent", area: "purchasing", icon: Truck, to: "/finance-pod/orders",
    does: "Drafts the PO from the approved request and the buyer's choice, then issues it and logs the acknowledgement.",
    people: "Buyer", busy: (o) => o.pos_waiting_for_me },
  { key: "capture", name: "Capture agent", area: "invoices", icon: FileSearch, to: "/finance-pod/invoices",
    does: "Reads the supplier's invoice: vendor, number, dates, PO and lines, every figure checked against the document.",
    people: "AP clerk", busy: (o) => o.invoices.captured ?? 0 },
  { key: "posting", name: "Posting agent", area: "invoices", icon: ReceiptText, to: "/finance-pod/invoices?status=duplicate",
    does: "Blocks and explains duplicates, then creates the invoice in the ERP with its source document.",
    people: "AP clerk", busy: (o) => o.invoices.duplicate ?? 0 },
  { key: "match", name: "Match agent", area: "invoices", icon: Scale, to: "/finance-pod/invoices",
    does: "Matches each line against the PO and what was received, with the tolerances, and explains the result.",
    people: "—" },
  { key: "exception", name: "Exception agent", area: "invoices", icon: MessageSquareWarning, to: "/finance-pod/exceptions",
    does: "Prepares the case and drafts the vendor query; after the buyer decides, re-matches and releases.",
    people: "Buyer", busy: (o) => o.exceptions_open.open ?? 0 },
  { key: "receipt", name: "Receipt agent", area: "invoices", icon: PackageCheck, to: "/finance-pod/exceptions?status=waiting_receipt",
    does: "Asks the receiver to confirm the delivery on their phone; the match runs again when they do.",
    people: "Receiver", busy: (o) => o.exceptions_open.waiting_receipt ?? 0 },
  { key: "payment", name: "Payment agent", area: "payments", icon: HandCoins, to: "/finance-pod/payments",
    does: "Proposes the payment run: what's due or can take a discount, grouped by currency and bank, with risk checks.",
    people: "AP analyst · treasury (two people release)", busy: (o) => sum(o.payment_runs, ["proposed", "partly_approved"]) },
  { key: "vendor", name: "Vendor agent", area: "payments", icon: Headset, to: "/finance-pod/vendor-queries",
    does: "Marks invoices paid and sends remittances; answers vendors' status questions from the records.",
    people: "AP analyst (disputes)", busy: (o) => o.queries.escalated ?? 0 },
  { key: "client-onboarding", name: "Client onboarding agent", area: "receivables", icon: FileCheck, to: "/finance-pod/clients",
    does: "Sends the secure application link, reads and validates the documents, screens sanctions and emails the client its gaps.",
    people: "Client · client services", busy: (o) => o.client_applications.submitted ?? 0 },
  { key: "credit", name: "Credit agent", area: "receivables", icon: Gauge, to: "/finance-pod/clients",
    does: "Scores the risk from the credit report, trade references and application; proposes a limit or deposit and terms.",
    people: "Credit controller (approves)", busy: (o) => o.client_applications.proposed ?? 0 },
  { key: "account", name: "Account agent", area: "receivables", icon: Network, to: "/finance-pod/clients",
    does: "Creates the approved client once in the ERP and the lab system, emails the account details, keeps both in sync.",
    people: "—" },
  { key: "monitor", name: "Monitor", area: "receivables", icon: Activity, to: "/finance-pod/credit-reviews",
    does: "Reviews each account as billing and payment history builds, and at its periodic review; proposes changes.",
    people: "Credit controller (approves)", busy: (o) => o.credit_reviews_open },
]
