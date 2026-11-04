import { useState, type FormEvent } from "react"
import { useParams } from "react-router"
import { useQuery } from "@tanstack/react-query"
import { Lock, ShieldCheck } from "lucide-react"

import { Alert } from "@/components/ui/alert"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Textarea } from "@/components/ui/textarea"
import { errorMessage } from "@/lib/api"

import { procurementApi } from "./procurement-api"

function Row({ id, label, children, hint }: { id: string; label: string; children: React.ReactNode; hint?: string }) {
  return (
    <div className="space-y-1">
      <Label htmlFor={id}>{label}</Label>
      {children}
      {hint && <p className="text-xs text-muted-foreground">{hint}</p>}
    </div>
  )
}

/** The vendor's secure onboarding form. No login: the single-use link is the key. */
export function VendorPortalPage() {
  const { token = "" } = useParams()
  const view = useQuery({ queryKey: ["vendor-portal", token], queryFn: () => procurementApi.portal(token), retry: false })
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [done, setDone] = useState(false)

  const submit = async (e: FormEvent<HTMLFormElement>) => {
    e.preventDefault()
    setBusy(true)
    setError(null)
    try {
      await procurementApi.submitPortal(token, new FormData(e.currentTarget))
      setDone(true)
    } catch (err) {
      setError(errorMessage(err, "Your form couldn't be sent. Check it and try again."))
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="min-h-svh bg-brand-page px-4 py-10">
      <div className="mx-auto max-w-2xl rounded-2xl border border-border bg-card p-6 shadow-sm">
        <p className="flex items-center gap-2 text-xs font-medium text-muted-foreground">
          <Lock className="size-3.5" aria-hidden /> Secure vendor form
        </p>
        {view.isPending ? (
          <p className="mt-4 text-sm text-muted-foreground">Loading…</p>
        ) : view.isError ? (
          <Alert className="mt-4">{errorMessage(view.error, "This link isn't valid any more. Ask your contact for a new one.")}</Alert>
        ) : done || view.data.status === "used" ? (
          <div className="mt-4 space-y-2">
            <h1 className="flex items-center gap-2 text-xl font-semibold">
              <ShieldCheck className="size-5 text-emerald-600" aria-hidden /> Thank you
            </h1>
            <p className="text-sm">
              We received your details. We'll call you on a number we already hold to confirm your bank account before any
              payment. You can close this page.
            </p>
          </div>
        ) : view.data.status === "expired" ? (
          <Alert className="mt-4">This link has expired. Ask your contact at {view.data.organisation} for a new one.</Alert>
        ) : (
          <form onSubmit={submit} className="mt-4 space-y-5">
            <div>
              <h1 className="text-xl font-semibold">
                {view.data.kind === "bank_change" ? "Update bank details" : "Supplier set-up"}: {view.data.vendor_name}
              </h1>
              <p className="mt-1 text-sm text-muted-foreground">
                For {view.data.organisation}. This link works once. We never ask for bank details by email.
              </p>
            </div>
            <fieldset className="grid gap-3 sm:grid-cols-2">
              <legend className="mb-2 text-sm font-semibold">Your business</legend>
              <Row id="legal_name" label="Legal name (as on your tax form)">
                <Input id="legal_name" name="legal_name" required maxLength={200} />
              </Row>
              <Row id="tax_form" label="Tax form">
                <select id="tax_form" name="tax_form" required className="flex h-10 w-full rounded-md border border-input bg-background px-3 text-sm">
                  <option value="W-9">W-9 (US)</option>
                  <option value="W-8BEN">W-8BEN (foreign individual)</option>
                  <option value="W-8BEN-E">W-8BEN-E (foreign entity)</option>
                </select>
              </Row>
              <Row id="tax_id" label="Tax ID (EIN / SSN / foreign TIN)">
                <Input id="tax_id" name="tax_id" required maxLength={40} />
              </Row>
              <Row id="phone" label="Phone">
                <Input id="phone" name="phone" maxLength={40} />
              </Row>
              <div className="sm:col-span-2">
                <Row id="address" label="Address">
                  <Textarea id="address" name="address" required minLength={5} rows={2} />
                </Row>
              </div>
            </fieldset>
            <fieldset className="grid gap-3 sm:grid-cols-2">
              <legend className="mb-2 text-sm font-semibold">Bank account for payments</legend>
              <Row id="bank_name" label="Bank">
                <Input id="bank_name" name="bank_name" required maxLength={200} />
              </Row>
              <Row id="account_name" label="Account holder name">
                <Input id="account_name" name="account_name" required maxLength={200} />
              </Row>
              <Row id="routing_number" label="Routing number (ABA) / sort code">
                <Input id="routing_number" name="routing_number" required autoComplete="off" maxLength={40} />
              </Row>
              <Row id="account_number" label="Account number">
                <Input id="account_number" name="account_number" required autoComplete="off" maxLength={40} />
              </Row>
            </fieldset>
            <fieldset className="grid gap-3 sm:grid-cols-2">
              <legend className="mb-2 text-sm font-semibold">Documents (PDF, PNG or JPEG, up to 10 MB)</legend>
              <Row id="tax_form_file" label="Signed tax form">
                <Input id="tax_form_file" name="tax_form_file" type="file" required accept=".pdf,.png,.jpg,.jpeg" />
              </Row>
              <Row id="bank_letter_file" label="Bank letter on the bank's letterhead" hint="Confirming the account holder and number.">
                <Input id="bank_letter_file" name="bank_letter_file" type="file" required accept=".pdf,.png,.jpg,.jpeg" />
              </Row>
              <Row id="insurance_file" label="Insurance / compliance (optional)">
                <Input id="insurance_file" name="insurance_file" type="file" accept=".pdf,.png,.jpg,.jpeg" />
              </Row>
            </fieldset>
            {error && <Alert>{error}</Alert>}
            <Button type="submit" disabled={busy}>
              {busy ? "Sending…" : "Send securely"}
            </Button>
          </form>
        )}
      </div>
    </div>
  )
}
