import { useState } from "react"
import { CircleCheck, Download, Landmark, LoaderCircle, TriangleAlert } from "lucide-react"
import { toast } from "sonner"

import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { useDataSources, useSourceRecords } from "@/features/data-sources/hooks"
import { errorMessage } from "@/lib/api"

import type { RunDetail, RunExternalAction } from "../api"
import { formatDateTime } from "../format"
import { useEvidencePack, useWriteBack } from "../hooks"

/** One ZIP with the run, documents' text, source snapshot and audit trail (with hashes). */
export function EvidencePackButton({ agentKey, run }: { agentKey: string; run: RunDetail }) {
  const pack = useEvidencePack(agentKey, run.id)
  return (
    <Button
      type="button"
      variant="outline"
      size="sm"
      onClick={() =>
        pack.mutate(undefined, {
          onError: (error) => toast.error(errorMessage(error, "Couldn't build the evidence pack")),
        })
      }
      disabled={pack.isPending}
    >
      {pack.isPending ? <LoaderCircle className="animate-spin" aria-hidden /> : <Download aria-hidden />}
      Evidence pack
    </Button>
  )
}

const NOTE = "quickbooks.bill_approval_note"
const CREATE = "quickbooks.bill_create"

const FIELD =
  "flex h-9 w-full rounded-md border border-input bg-background px-2 text-sm focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/20 focus-visible:outline-none"

function Receipt({ action }: { action: RunExternalAction }) {
  const r = action.receipt ?? {}
  const what =
    action.kind === CREATE
      ? r.already_present
        ? `bill ${String(r.bill_id)} with number ${String(r.doc_number)} already existed for ${String(r.vendor)}, so none was created`
        : `bill ${String(r.bill_id)} for ${String(r.vendor)}, ${String(r.amount)} to ${String(r.account)}`
      : `bill ${String(r.bill_id ?? "")}${r.already_present ? ", note was already there" : ""}`
  return (
    <p className="flex items-start gap-2 text-sm">
      <CircleCheck className="mt-0.5 size-4 shrink-0 text-emerald-600" aria-hidden />
      <span>
        {action.label} ({what}) · {formatDateTime(action.completed_at)}
      </span>
    </p>
  )
}

/** For an invoice entered by hand: pick the company and expense account, confirm, create. */
function CreateBillForm({ agentKey, run }: { agentKey: string; run: RunDetail }) {
  const writeBack = useWriteBack(agentKey, run.id)
  const sources = useDataSources()
  const companies = (sources.data ?? []).filter((s) => s.kind === "quickbooks" && s.status === "connected")
  const [sourceId, setSourceId] = useState<string | null>(null)
  const source = sourceId ?? companies[0]?.id ?? null
  const [search, setSearch] = useState(String(run.input.proposed_gl_account ?? ""))
  const accounts = useSourceRecords(source, "account", search.trim())
  const [accountId, setAccountId] = useState("")
  const [confirming, setConfirming] = useState(false)
  const account = accounts.data?.find((a) => a.external_id === accountId)
  const company = companies.find((c) => c.id === source)

  const create = () =>
    source &&
    writeBack.mutate(
      { source_id: source, account_id: accountId },
      {
        onSuccess: () => setConfirming(false),
        onError: (error) => toast.error(errorMessage(error, "Couldn't create the bill in QuickBooks")),
      },
    )

  return (
    <div className="space-y-3">
      <p className="text-xs text-muted-foreground">
        Creates a bill for {String(run.input.supplier)}, number {String(run.input.invoice_number)}, total{" "}
        {String(run.input.invoice_total)}, in your QuickBooks. The vendor must exist there. If the vendor already has a
        bill with this number, nothing new is created.
      </p>
      {companies.length > 1 && (
        <div className="space-y-1">
          <Label htmlFor="wb-company" className="text-xs">
            QuickBooks company
          </Label>
          <select id="wb-company" className={FIELD} value={source ?? ""} onChange={(e) => setSourceId(e.target.value)}>
            {companies.map((c) => (
              <option key={c.id} value={c.id}>
                {c.name}
              </option>
            ))}
          </select>
        </div>
      )}
      <div className="space-y-1">
        <Label htmlFor="wb-account-search" className="text-xs">
          Expense account
        </Label>
        <Input
          id="wb-account-search"
          className="h-9 text-sm"
          placeholder="Search accounts by number or name"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
        />
        <select
          aria-label="Expense account"
          className={FIELD}
          value={accountId}
          onChange={(e) => setAccountId(e.target.value)}
        >
          <option value="">{accounts.isPending ? "Loading accounts…" : "Choose an account"}</option>
          {accounts.data?.map((a) => (
            <option key={a.external_id} value={a.external_id}>
              {[a.data.number, a.data.name].filter(Boolean).join(" ")}
              {a.data.account_type ? ` (${String(a.data.account_type)})` : ""}
            </option>
          ))}
        </select>
      </div>
      {confirming && account ? (
        <div className="space-y-2 rounded-md border border-amber-300 bg-amber-50 p-3 text-sm text-amber-950" role="alert">
          <p>
            Create this bill in <strong>{company?.name}</strong>, expensed to{" "}
            <strong>{[account.data.number, account.data.name].filter(Boolean).join(" ")}</strong>? It can only be
            changed or deleted in QuickBooks afterwards.
          </p>
          <div className="flex gap-2">
            <Button type="button" size="sm" onClick={create} disabled={writeBack.isPending}>
              {writeBack.isPending && <LoaderCircle className="animate-spin" aria-hidden />}
              Create bill
            </Button>
            <Button type="button" size="sm" variant="outline" onClick={() => setConfirming(false)}>
              Cancel
            </Button>
          </div>
        </div>
      ) : (
        <Button type="button" size="sm" onClick={() => setConfirming(true)} disabled={!account}>
          Create bill in QuickBooks…
        </Button>
      )}
    </div>
  )
}

/** After approval: note it on the QuickBooks bill the run came from (or create the bill for an
 * invoice entered by hand), and show the receipt. */
export function WriteBackPanel({ agentKey, run }: { agentKey: string; run: RunDetail }) {
  const writeBack = useWriteBack(agentKey, run.id)
  const { can_write_back: can, write_back: mode, write_back_blocked_reason: blocked } = run.permissions
  const action = run.actions.find((a) => a.kind === NOTE || a.kind === CREATE)
  if (!action && !mode) return null

  return (
    <div className="space-y-2 rounded-md border bg-background p-3">
      <h3 className="flex items-center gap-2 text-sm font-semibold text-brand-navy">
        <Landmark className="size-4" aria-hidden />
        QuickBooks
      </h3>
      {action?.status === "succeeded" && <Receipt action={action} />}
      {action?.status === "queued" && (
        <p className="flex items-center gap-2 text-sm text-muted-foreground" role="status">
          <LoaderCircle className="size-4 animate-spin" aria-hidden /> Writing to QuickBooks…
        </p>
      )}
      {action?.status === "failed" && (
        <p className="flex items-start gap-2 text-sm text-red-800">
          <TriangleAlert className="mt-0.5 size-4 shrink-0" aria-hidden />
          Write-back failed: {action.error}
        </p>
      )}
      {blocked && action?.status !== "succeeded" && <p className="text-xs text-muted-foreground">{blocked}</p>}
      {can && mode === "create_bill" && <CreateBillForm agentKey={agentKey} run={run} />}
      {can && mode === "note" && (
        <>
          <p className="text-xs text-muted-foreground">
            Adds an approval note to the bill in your QuickBooks. Amounts and coding are not changed.
          </p>
          <Button
            type="button"
            size="sm"
            onClick={() =>
              writeBack.mutate(undefined, {
                onError: (error) => toast.error(errorMessage(error, "Couldn't write back to QuickBooks")),
              })
            }
            disabled={writeBack.isPending}
          >
            {writeBack.isPending && <LoaderCircle className="animate-spin" aria-hidden />}
            {action?.status === "failed" ? "Try again" : "Note approval in QuickBooks"}
          </Button>
        </>
      )}
    </div>
  )
}
