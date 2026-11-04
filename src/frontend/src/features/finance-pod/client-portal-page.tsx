import { useState, type FormEvent, type ReactNode } from "react"
import { useParams } from "react-router"
import { useQuery } from "@tanstack/react-query"
import { CircleCheck, Lock, Plus, ShieldCheck, Trash2 } from "lucide-react"

import { Alert } from "@/components/ui/alert"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Textarea } from "@/components/ui/textarea"
import { errorMessage } from "@/lib/api"

import { clientsApi, type ClientDocumentKind, type ClientPortalView, type Contact } from "./clients-api"
import { DOC_KIND } from "./labels"

function Row({ id, label, children, hint }: { id: string; label: string; children: ReactNode; hint?: string }) {
  return (
    <div className="space-y-1">
      <Label htmlFor={id}>{label}</Label>
      {children}
      {hint && <p className="text-xs text-muted-foreground">{hint}</p>}
    </div>
  )
}

const text = (v: unknown) => (v === null || v === undefined ? undefined : String(v))

function ApplicationForm({ token, view, onDone }: { token: string; view: ClientPortalView; onDone: () => void }) {
  const prev = view.previous
  const held = new Set(view.documents_held)
  const [contacts, setContacts] = useState<Contact[]>(prev.contacts?.length ? prev.contacts : [{ name: "", email: "", phone: "", role: "" }])
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const submit = async (e: FormEvent<HTMLFormElement>) => {
    e.preventDefault()
    setBusy(true)
    setError(null)
    const form = new FormData(e.currentTarget)
    form.set("country", String(form.get("country") ?? "").trim().toUpperCase())
    form.set("contacts", JSON.stringify(contacts.filter((c) => c.name.trim() || c.email.trim())))
    for (const key of ["registration_file", "tax_file", "credit_report_file"]) {
      const value = form.get(key)
      if (value instanceof File && !value.name) form.delete(key) // nothing chosen
    }
    const references = form.getAll("trade_reference_files").filter((f) => f instanceof File && f.name)
    form.delete("trade_reference_files")
    references.forEach((f) => form.append("trade_reference_files", f))
    try {
      await clientsApi.submitPortal(token, form)
      onDone()
    } catch (err) {
      setError(errorMessage(err, "Your application couldn't be sent. Check it and try again."))
    } finally {
      setBusy(false)
    }
  }

  const setContact = (i: number, patch: Partial<Contact>) => setContacts((cs) => cs.map((c, j) => (j === i ? { ...c, ...patch } : c)))
  const file = (name: string, kind: ClientDocumentKind, label: string, hint?: string, multiple = false) => (
    <Row id={name} label={label} hint={held.has(kind) ? "Already received: send again only to replace it." : hint}>
      <Input id={name} name={name} type="file" multiple={multiple} accept=".pdf,.png,.jpg,.jpeg" />
    </Row>
  )

  return (
    <form onSubmit={submit} className="mt-4 space-y-5">
      <div>
        <h1 className="text-xl font-semibold">Client account application: {view.client_name}</h1>
        <p className="mt-1 text-sm text-muted-foreground">For {view.organisation}. This link works once.</p>
      </div>
      {view.gaps.length > 0 && (
        <div className="rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 text-sm text-amber-950">
          <p className="font-medium">Please complete the following; your earlier answers are filled in:</p>
          <ul className="mt-1 list-disc pl-5">
            {view.gaps.map((g) => (
              <li key={g}>{g}</li>
            ))}
          </ul>
        </div>
      )}
      <fieldset className="grid gap-3 sm:grid-cols-2">
        <legend className="mb-2 text-sm font-semibold">Your company</legend>
        <Row id="legal_name" label="Legal name (as registered)">
          <Input id="legal_name" name="legal_name" required maxLength={200} defaultValue={text(prev.legal_name)} />
        </Row>
        <Row id="tax_id" label="Tax ID (EIN, or your tax registration number)">
          <Input id="tax_id" name="tax_id" required maxLength={40} placeholder="12-3456789" />
        </Row>
        <Row id="country" label="Country (2-letter code)">
          <Input id="country" name="country" required maxLength={2} className="uppercase" defaultValue={text(prev.country) ?? "US"} />
        </Row>
        <Row id="years_trading" label="Years trading">
          <Input id="years_trading" name="years_trading" inputMode="numeric" maxLength={4} defaultValue={text(prev.years_trading)} />
        </Row>
        <div className="sm:col-span-2">
          <Row id="address" label="Registered address">
            <Textarea id="address" name="address" required minLength={5} rows={2} defaultValue={text(prev.address)} />
          </Row>
        </div>
        <Row id="phone" label="Phone">
          <Input id="phone" name="phone" maxLength={40} defaultValue={text(prev.phone)} />
        </Row>
        <Row id="website" label="Website">
          <Input id="website" name="website" maxLength={200} defaultValue={text(prev.website)} />
        </Row>
      </fieldset>

      <fieldset className="space-y-2">
        <legend className="mb-2 text-sm font-semibold">Contacts</legend>
        <Row id="billing_email" label="Billing email (where invoices go)">
          <Input id="billing_email" name="billing_email" type="email" required defaultValue={text(prev.billing_email)} />
        </Row>
        {contacts.map((c, i) => (
          <div key={i} className="grid gap-2 rounded-lg border border-border/70 p-2 sm:grid-cols-[1fr_1fr_0.8fr_0.8fr_auto]">
            <Input aria-label="Contact name" placeholder="Name" value={c.name} required={i === 0} onChange={(e) => setContact(i, { name: e.target.value })} />
            <Input aria-label="Contact email" placeholder="Email" type="email" value={c.email} required={i === 0} onChange={(e) => setContact(i, { email: e.target.value })} />
            <Input aria-label="Contact phone" placeholder="Phone" value={c.phone ?? ""} onChange={(e) => setContact(i, { phone: e.target.value })} />
            <Input aria-label="Contact role" placeholder="Role" value={c.role ?? ""} onChange={(e) => setContact(i, { role: e.target.value })} />
            <Button type="button" size="icon" variant="ghost" aria-label="Remove contact" disabled={contacts.length === 1} onClick={() => setContacts((cs) => cs.filter((_, j) => j !== i))}>
              <Trash2 aria-hidden />
            </Button>
          </div>
        ))}
        {contacts.length < 5 && (
          <Button type="button" size="sm" variant="outline" onClick={() => setContacts((cs) => [...cs, { name: "", email: "", phone: "", role: "" }])}>
            <Plus aria-hidden /> Add a contact
          </Button>
        )}
      </fieldset>

      <fieldset className="grid gap-3 sm:grid-cols-2">
        <legend className="mb-2 text-sm font-semibold">Credit terms you'd like</legend>
        <Row id="currency" label="Billing currency">
          <select id="currency" name="currency" defaultValue={text(prev.currency) ?? "USD"} className="flex h-10 w-full rounded-md border border-input bg-background px-3 text-sm">
            {["USD", "EUR", "GBP", "CAD", "AUD", "INR"].map((c) => (
              <option key={c}>{c}</option>
            ))}
          </select>
        </Row>
        <Row id="requested_terms" label="Payment terms">
          <Input id="requested_terms" name="requested_terms" maxLength={40} placeholder="Net 30" defaultValue={text(prev.requested_terms)} />
        </Row>
        <Row id="requested_limit" label="Credit limit requested">
          <Input id="requested_limit" name="requested_limit" inputMode="decimal" defaultValue={text(prev.requested_limit)} />
        </Row>
        <Row id="expected_monthly" label="Expected monthly spend">
          <Input id="expected_monthly" name="expected_monthly" inputMode="decimal" defaultValue={text(prev.expected_monthly)} />
        </Row>
      </fieldset>

      <fieldset className="grid gap-3 sm:grid-cols-2">
        <legend className="mb-2 text-sm font-semibold">Documents (PDF, PNG or JPEG, up to 10 MB)</legend>
        {file("registration_file", "registration", `${DOC_KIND.registration} (certificate of incorporation)`)}
        {file("tax_file", "tax", `${DOC_KIND.tax} (W-9 or tax registration)`)}
        {file("credit_report_file", "credit_report", "Credit report (optional)", "A recent bureau report (D&B, Experian…) helps us offer credit rather than a deposit.")}
        {file("trade_reference_files", "trade_reference", "Trade references (optional, up to 3)", "Letters from suppliers who give you credit.", true)}
      </fieldset>
      {error && <Alert>{error}</Alert>}
      <Button type="submit" disabled={busy}>
        {busy ? "Sending…" : "Send application securely"}
      </Button>
    </form>
  )
}

/** The client's secure account application. No login: the single-use link is the key. */
export function ClientPortalPage() {
  const { token = "" } = useParams()
  const view = useQuery({ queryKey: ["client-portal", token], queryFn: () => clientsApi.portal(token), retry: false })
  const [done, setDone] = useState(false)
  return (
    <div className="min-h-svh bg-brand-page px-4 py-10">
      <div className="mx-auto max-w-2xl rounded-2xl border border-border bg-card p-6 shadow-sm">
        <p className="flex items-center gap-2 text-xs font-medium text-muted-foreground">
          <Lock className="size-3.5" aria-hidden /> Secure client application
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
              We received your application. If anything is missing we'll email you a new link; once your terms are approved we'll send
              your account number. You can close this page.
            </p>
            <p className="flex items-center gap-1.5 text-xs text-muted-foreground">
              <CircleCheck className="size-3.5" aria-hidden /> Your documents are stored securely.
            </p>
          </div>
        ) : view.data.status === "expired" ? (
          <Alert className="mt-4">This link has expired. Ask your contact at {view.data.organisation} for a new one.</Alert>
        ) : (
          <ApplicationForm token={token} view={view.data} onDone={() => setDone(true)} />
        )}
      </div>
    </div>
  )
}
