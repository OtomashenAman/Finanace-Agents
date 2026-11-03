import { useState, type FormEvent } from "react"
import { useParams } from "react-router"
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { CircleCheck, LoaderCircle, Plus, ShieldCheck, Trash2, Upload } from "lucide-react"

import { Alert } from "@/components/ui/alert"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Textarea } from "@/components/ui/textarea"
import { errorMessage } from "@/lib/api"

import { clientPortalApi, type ClientApplication } from "./api"

const NAMES: Record<string, string> = {
  tax_form: "Tax form (W-9, or W-8BEN-E outside the US)",
  registration: "Company registration or other compliance papers",
}

const EMPTY: ClientApplication = {
  legal_name: "",
  trading_name: "",
  tax_id: "",
  country: "United States",
  address: "",
  billing_email: "",
  established_year: null,
  requested_limit: "0",
  requested_terms_days: 30,
  trade_references: [],
}

/** A client's account application: no account, only the signed link from the invitation.
 *  They upload their documents and submit the form; nothing of ours is shown. */
export function ClientPortalPage() {
  const { token = "" } = useParams()
  const queries = useQueryClient()
  const key = ["client-portal", token]
  const view = useQuery({ queryKey: key, queryFn: () => clientPortalApi.view(token), retry: false })
  const refresh = () => void queries.invalidateQueries({ queryKey: key })
  const upload = useMutation({ mutationFn: clientPortalApi.upload, onSuccess: refresh })
  const apply = useMutation({ mutationFn: clientPortalApi.apply, onSuccess: refresh })
  const [kind, setKind] = useState("tax_form")
  const [file, setFile] = useState<File | null>(null)
  const [picker, setPicker] = useState(0) // a new file input after each upload
  const [form, setForm] = useState<ClientApplication | null>(null)
  const current = form ?? view.data?.application ?? EMPTY
  const set = (patch: Partial<ClientApplication>) => setForm({ ...current, ...patch })

  const send = (e: FormEvent) => {
    e.preventDefault()
    if (file) upload.mutate({ token, kind, file }, { onSuccess: () => { setFile(null); setPicker((n) => n + 1) } })
  }
  const submit = (e: FormEvent) => {
    e.preventDefault()
    apply.mutate({
      token,
      body: {
        ...current,
        trading_name: current.trading_name || null,
        tax_id: current.tax_id || null,
        established_year: current.established_year || null,
        trade_references: current.trade_references.filter((r) => r.company && r.contact_email),
      },
    })
  }

  return (
    <main className="mx-auto min-h-screen max-w-2xl px-4 py-10">
      <div className="mb-6 flex items-center gap-2 text-brand-navy">
        <ShieldCheck className="size-6" aria-hidden />
        <h1 className="text-xl font-semibold">Open an account</h1>
      </div>
      {view.isLoading && <LoaderCircle className="size-6 animate-spin text-primary" aria-label="Loading" />}
      {view.isError && <Alert>{errorMessage(view.error, "This link isn't valid any more. Ask your contact for a new one.")}</Alert>}
      {view.data && (
        <div className="space-y-6">
          <p className="text-sm">
            Please complete the application for <span className="font-semibold">{view.data.client_name}</span> and upload the
            documents below. This page works until {new Date(view.data.expires_at).toLocaleDateString()}.
          </p>

          <section className="space-y-3">
            <h2 className="text-sm font-semibold">1. Documents</h2>
            <ul className="space-y-2 text-sm">
              {view.data.required.map((k) => {
                const done = view.data.uploaded.filter((u) => u.kind === k)
                return (
                  <li key={k} className="flex items-start gap-2">
                    <CircleCheck className={`mt-0.5 size-4 shrink-0 ${done.length ? "text-emerald-600" : "text-muted-foreground"}`} aria-hidden />
                    <span>
                      {NAMES[k]}
                      {done.map((d) => (
                        <span key={d.filename + d.uploaded_at} className="block text-xs text-muted-foreground">
                          {d.filename} · {new Date(d.uploaded_at).toLocaleString()}
                        </span>
                      ))}
                    </span>
                  </li>
                )
              })}
            </ul>
            {view.data.open && (
              <form onSubmit={send} className="space-y-3 rounded-lg border p-4">
                {upload.error && <Alert>{errorMessage(upload.error, "Upload failed")}</Alert>}
                <select aria-label="Document" className="flex h-10 w-full rounded-md border border-input bg-background px-3 text-sm"
                  value={kind} onChange={(e) => setKind(e.target.value)}>
                  {Object.entries(NAMES).map(([k, n]) => <option key={k} value={k}>{n}</option>)}
                </select>
                <Input key={picker} type="file" aria-label="File" accept=".pdf,.png,.jpg,.jpeg,.txt,.docx" onChange={(e) => setFile(e.target.files?.[0] ?? null)} />
                <Button type="submit" disabled={!file || upload.isPending}>
                  {upload.isPending ? <LoaderCircle className="animate-spin" aria-hidden /> : <Upload aria-hidden />} Upload
                </Button>
              </form>
            )}
          </section>

          <section className="space-y-3">
            <h2 className="text-sm font-semibold">2. Application</h2>
            {!view.data.open ? (
              <p role="status" className="rounded-md border border-emerald-200 bg-emerald-50 px-3.5 py-3 text-sm text-emerald-800">
                Thank you: your application is with our credit team. We'll be in touch.
              </p>
            ) : (
              <form onSubmit={submit} className="space-y-3 rounded-lg border p-4 text-sm">
                {apply.error && <Alert>{errorMessage(apply.error, "Couldn't submit the application")}</Alert>}
                {apply.isSuccess && (
                  <p role="status" className="flex items-center gap-2 rounded-md border border-emerald-200 bg-emerald-50 px-3.5 py-3 text-emerald-800">
                    <CircleCheck className="size-4 shrink-0" aria-hidden /> Application received. We'll email you if anything is missing.
                  </p>
                )}
                <div className="grid gap-3 sm:grid-cols-2">
                  <label className="space-y-1"><span className="font-medium">Legal name *</span>
                    <Input value={current.legal_name} onChange={(e) => set({ legal_name: e.target.value })} required minLength={2} /></label>
                  <label className="space-y-1"><span className="font-medium">Trading name</span>
                    <Input value={current.trading_name ?? ""} onChange={(e) => set({ trading_name: e.target.value })} /></label>
                  <label className="space-y-1"><span className="font-medium">Tax ID (EIN, or VAT abroad)</span>
                    <Input value={current.tax_id ?? ""} onChange={(e) => set({ tax_id: e.target.value })} /></label>
                  <label className="space-y-1"><span className="font-medium">Country *</span>
                    <Input value={current.country} onChange={(e) => set({ country: e.target.value })} required /></label>
                  <label className="space-y-1 sm:col-span-2"><span className="font-medium">Address *</span>
                    <Textarea rows={2} value={current.address} onChange={(e) => set({ address: e.target.value })} required minLength={5} /></label>
                  <label className="space-y-1"><span className="font-medium">Where invoices go (email) *</span>
                    <Input type="email" value={current.billing_email} onChange={(e) => set({ billing_email: e.target.value })} required /></label>
                  <label className="space-y-1"><span className="font-medium">Established (year)</span>
                    <Input type="number" min={1800} max={2100} value={current.established_year ?? ""}
                      onChange={(e) => set({ established_year: e.target.value ? Number(e.target.value) : null })} /></label>
                  <label className="space-y-1"><span className="font-medium">Credit limit requested (0: pay on deposit) *</span>
                    <Input type="number" min={0} step="any" value={current.requested_limit} onChange={(e) => set({ requested_limit: e.target.value })} required /></label>
                  <label className="space-y-1"><span className="font-medium">Payment terms requested (days) *</span>
                    <Input type="number" min={0} max={120} value={current.requested_terms_days}
                      onChange={(e) => set({ requested_terms_days: Number(e.target.value) })} required /></label>
                </div>
                <div className="space-y-2">
                  <p className="font-medium">Trade references (needed for credit terms)</p>
                  {current.trade_references.map((r, i) => (
                    <div key={i} className="grid gap-2 sm:grid-cols-[minmax(0,1fr)_minmax(0,1fr)_auto]">
                      <Input aria-label="Reference company" placeholder="Company" value={r.company}
                        onChange={(e) => set({ trade_references: current.trade_references.map((x, j) => (j === i ? { ...x, company: e.target.value } : x)) })} />
                      <Input aria-label="Reference email" type="email" placeholder="Contact email" value={r.contact_email}
                        onChange={(e) => set({ trade_references: current.trade_references.map((x, j) => (j === i ? { ...x, contact_email: e.target.value } : x)) })} />
                      <Button type="button" variant="ghost" size="icon" aria-label="Remove reference"
                        onClick={() => set({ trade_references: current.trade_references.filter((_, j) => j !== i) })}>
                        <Trash2 className="size-4" aria-hidden />
                      </Button>
                    </div>
                  ))}
                  {current.trade_references.length < 5 && (
                    <Button type="button" variant="outline" size="sm"
                      onClick={() => set({ trade_references: [...current.trade_references, { company: "", contact_email: "" }] })}>
                      <Plus className="size-4" aria-hidden /> Add a reference
                    </Button>
                  )}
                </div>
                <Button type="submit" disabled={apply.isPending}>
                  {apply.isPending && <LoaderCircle className="animate-spin" aria-hidden />} Submit the application
                </Button>
              </form>
            )}
          </section>
        </div>
      )}
    </main>
  )
}
