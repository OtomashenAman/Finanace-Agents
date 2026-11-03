import { useState, type FormEvent } from "react"
import { useNavigate } from "react-router"
import { LoaderCircle, Plus } from "lucide-react"
import { toast } from "sonner"

import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Card } from "@/features/service-pod/components/bits"
import { selectClass } from "@/features/service-pod/ui"
import { errorMessage } from "@/lib/api"

import { useBillingIntake, useFinanceMe, useFinanceWorkflows, useIntake, useOpenCase, useSourceCatalogue, useSources } from "../hooks"

function lastMonth(): string {
  const d = new Date()
  d.setDate(1)
  d.setMonth(d.getMonth() - 1)
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}`
}

/** Open a case on the newest snapshot that supplies what the workflow needs: a purchase
 *  request (new, or one already raised in ERPNext) or a vendor onboarding. */
export function NewCase() {
  const me = useFinanceMe()
  const workflows = useFinanceWorkflows()
  const open = useOpenCase()
  const navigate = useNavigate()
  const canOpen = (me.data?.is_admin ? workflows.data?.map((w) => w.key) : me.data?.can_open) ?? []
  const choices = (workflows.data ?? []).filter((w) => canOpen.includes(w.key))
  const [workflow, setWorkflow] = useState<string | null>(null)
  const chosen = workflow ?? choices[0]?.key ?? null
  const sources = useSources(chosen)
  const [snapshotId, setSnapshotId] = useState("")
  const snapshot = snapshotId || sources.data?.[0]?.id || ""
  const party = chosen === "ap_vendor_onboarding" || chosen === "ar_client_account"
  const catalogue = useSourceCatalogue(party ? null : snapshot || null, chosen)
  const intake = useIntake()
  const billingIntake = useBillingIntake()
  const [submission, setSubmission] = useState("")
  const [bill, setBill] = useState("")
  const [title, setTitle] = useState("")
  const [erpRequest, setErpRequest] = useState("")
  const [vendorName, setVendorName] = useState("")
  const [vendorEmail, setVendorEmail] = useState("")
  const [period, setPeriod] = useState(lastMonth)
  const [showing, setShowing] = useState(false)
  if (choices.length === 0) return null

  const submit = (e: FormEvent) => {
    e.preventDefault()
    if (!chosen || !snapshot) return
    const selection =
      chosen === "ap_vendor_onboarding"
        ? { vendor_name: vendorName, contact_email: vendorEmail }
        : chosen === "ar_client_account"
          ? { client_name: vendorName, contact_email: vendorEmail }
          : chosen === "ar_billing"
            ? { submission_id: submission }
          : chosen === "ap_invoice_match"
          ? { bill_id: bill }
          : chosen === "ap_month_close"
            ? { period }
            : erpRequest
            ? { erp_request_id: erpRequest }
            : {}
    open.mutate(
      {
        workflow: chosen,
        snapshot_id: snapshot,
        title:
          title ||
          (chosen === "ap_vendor_onboarding"
            ? `Onboard ${vendorName}`
            : chosen === "ar_client_account"
              ? `Open an account for ${vendorName}`
              : chosen === "ar_billing"
                ? `Bill ${catalogue.data?.billable_submissions.find((b) => b.id === submission)?.name ?? ""} · ${submission}`
              : chosen === "ap_invoice_match"
              ? `Invoice ${catalogue.data?.incoming_invoices.find((b) => b.id === bill)?.name ?? bill}`
              : chosen === "ap_month_close"
                ? `AP close ${period}`
                : "Purchase request"),
        selection,
      },
      {
        onSuccess: (c) => {
          toast.success(`${c.reference} opened`)
          navigate(`/finance/cases/${c.id}`)
        },
        onError: (error) => toast.error(errorMessage(error, "Couldn't open the case")),
      },
    )
  }

  return (
    <Card
      title="Start"
      actions={
        !showing && (
          <Button size="sm" onClick={() => setShowing(true)}>
            <Plus className="size-4" aria-hidden /> New
          </Button>
        )
      }
    >
      {!showing ? (
        <p className="text-sm text-muted-foreground">Raise a purchase request, onboard a vendor, match an invoice or close a month.</p>
      ) : (
        <form onSubmit={submit} className="space-y-3">
          <div className="grid gap-2 sm:grid-cols-2">
            <label className="space-y-1 text-sm">
              <span className="font-medium">Workflow</span>
              <select className={selectClass} value={chosen ?? ""} onChange={(e) => { setWorkflow(e.target.value); setSnapshotId("") }}>
                {choices.map((w) => <option key={w.key} value={w.key}>{w.name}</option>)}
              </select>
            </label>
            <label className="space-y-1 text-sm">
              <span className="font-medium">Source data</span>
              <select className={selectClass} value={snapshot} onChange={(e) => setSnapshotId(e.target.value)} required>
                {sources.data?.length === 0 && <option value="">No usable snapshot: ask a Finance Admin for one</option>}
                {sources.data?.map((s) => (
                  <option key={s.id} value={s.id}>
                    {s.company_name} · {s.entity.code} · {new Date(s.imported_at).toLocaleString()}
                    {s.is_demo ? " (demo)" : ""}
                  </option>
                ))}
              </select>
            </label>
          </div>
          {chosen === "ap_purchase_request" && (catalogue.data?.purchase_requests.length ?? 0) > 0 && (
            <label className="block space-y-1 text-sm">
              <span className="font-medium">Start from a request already in ERPNext (optional)</span>
              <select className={selectClass} value={erpRequest} onChange={(e) => setErpRequest(e.target.value)}>
                <option value="">A new request</option>
                {catalogue.data?.purchase_requests.map((r) => (
                  <option key={r.id} value={r.id}>{r.id} · {r.name} ({r.detail})</option>
                ))}
              </select>
            </label>
          )}
          {chosen === "ap_invoice_match" && (
            <div className="space-y-2">
              <select aria-label="Incoming invoice" className={selectClass} value={bill} onChange={(e) => setBill(e.target.value)} required>
                <option value="">An incoming invoice (ERPNext draft)…</option>
                {catalogue.data?.incoming_invoices.map((b) => (
                  <option key={b.id} value={b.id}>{b.id} · {b.name} · {b.detail}</option>
                ))}
              </select>
              <Button type="button" size="sm" variant="outline" disabled={!snapshot || intake.isPending}
                onClick={() => intake.mutate(snapshot, {
                  onSuccess: (r) => toast.success(
                    r.opened.length ? `Opened ${r.opened.join(", ")}` : "Every incoming invoice already has a case",
                  ),
                  onError: (error) => toast.error(errorMessage(error, "Couldn't take the invoices in")),
                })}>
                Or open a case for every new invoice
              </Button>
            </div>
          )}
          {chosen === "ar_billing" && (
            <div className="space-y-2">
              <select aria-label="Lab submission" className={selectClass} value={submission} onChange={(e) => setSubmission(e.target.value)} required>
                <option value="">A submission whose report is issued…</option>
                {catalogue.data?.billable_submissions.map((b) => (
                  <option key={b.id} value={b.id}>{b.id} · {b.name} · {b.detail}</option>
                ))}
              </select>
              <Button type="button" size="sm" variant="outline" disabled={!snapshot || billingIntake.isPending}
                onClick={() => billingIntake.mutate(snapshot, {
                  onSuccess: (r) => toast.success(
                    r.opened.length ? `Opened ${r.opened.join(", ")}` : "Every billable submission already has a case",
                  ),
                  onError: (error) => toast.error(errorMessage(error, "Couldn't take the submissions in")),
                })}>
                Or open a case for every billable submission
              </Button>
            </div>
          )}
          {chosen === "ap_month_close" && (
            <label className="block space-y-1 text-sm">
              <span className="font-medium">Month to close</span>
              <Input type="month" value={period} onChange={(e) => setPeriod(e.target.value)} required className="max-w-48" />
              <span className="block text-xs text-muted-foreground">The source data must be taken after the month ends.</span>
            </label>
          )}
          {party && (
            <div className="grid gap-2 sm:grid-cols-2">
              <Input placeholder={chosen === "ar_client_account" ? "Client's name" : "Vendor's legal name"} value={vendorName}
                onChange={(e) => setVendorName(e.target.value)} required />
              <Input placeholder="Their contact email" type="email" value={vendorEmail} onChange={(e) => setVendorEmail(e.target.value)} required />
            </div>
          )}
          <Input placeholder="Title (optional)" value={title} onChange={(e) => setTitle(e.target.value)} maxLength={200} />
          <div className="flex gap-2">
            <Button type="submit" size="sm" disabled={open.isPending || !snapshot}>
              {open.isPending && <LoaderCircle className="size-4 animate-spin" aria-hidden />} Open
            </Button>
            <Button type="button" size="sm" variant="ghost" onClick={() => setShowing(false)}>Cancel</Button>
          </div>
        </form>
      )}
    </Card>
  )
}
