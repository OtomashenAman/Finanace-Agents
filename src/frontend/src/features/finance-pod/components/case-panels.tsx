import { useState, type FormEvent } from "react"
import { Download, LoaderCircle, Send, Upload } from "lucide-react"
import { toast } from "sonner"

import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Card } from "@/features/service-pod/components/bits"
import { ARTIFACT_KIND } from "@/features/service-pod/labels"
import { selectClass } from "@/features/service-pod/ui"
import { apiDownload, errorMessage } from "@/lib/api"
import { cn } from "@/lib/utils"

import { financeApi, type CaseDetail } from "../api"
import { useCaseAction, useSendMessage, useSources, useTaskAction, useUpload } from "../hooks"

const KINDS = ["invoice_copy", "quote", "compliance", "supporting", "other", "tax_form", "bank_letter", "vendor_statement"] as const

function fail(error: unknown, fallback: string) {
  toast.error(errorMessage(error, fallback))
}

export function DocumentsPanel({ c }: { c: CaseDetail }) {
  const upload = useUpload()
  const [kind, setKind] = useState<string>(
    c.workflow === "ap_vendor_onboarding"
      ? "compliance"
      : c.workflow === "ap_invoice_match"
        ? "invoice_copy"
        : c.workflow === "ap_month_close"
          ? "vendor_statement"
          : "quote",
  )
  const [file, setFile] = useState<File | null>(null)
  const submit = (e: FormEvent) => {
    e.preventDefault()
    if (!file) return
    upload.mutate(
      { caseId: c.id, kind, file },
      { onSuccess: () => { toast.success(`${file.name} added`); setFile(null) }, onError: (e) => fail(e, "Upload failed") },
    )
  }
  return (
    <Card title="Documents" hint="Tax forms and bank letters only count when the vendor uploads them through the portal.">
      {c.artifacts.length > 0 && (
        <ul className="mb-3 space-y-1 text-sm">
          {c.artifacts.map((a) => (
            <li key={a.id} className="flex items-center justify-between gap-2">
              <span className="min-w-0 truncate">
                <span className="font-medium">{a.filename}</span>{" "}
                <span className="text-xs text-muted-foreground">
                  {ARTIFACT_KIND[a.kind]} · {a.channel === "vendor_portal" ? "vendor portal" : a.uploaded_by}
                </span>
              </span>
              <Button variant="ghost" size="icon" aria-label={`Download ${a.filename}`}
                onClick={() => void apiDownload(financeApi.documentUrl(a.id), a.filename)}>
                <Download className="size-4" aria-hidden />
              </Button>
            </li>
          ))}
        </ul>
      )}
      {c.status === "draft" && (
        <form onSubmit={submit} className="flex flex-wrap items-center gap-2">
          <select aria-label="Kind" className={cn(selectClass, "h-9 w-44")} value={kind} onChange={(e) => setKind(e.target.value)}>
            {KINDS.map((k) => (
              <option key={k} value={k}>
                {ARTIFACT_KIND[k]}
              </option>
            ))}
          </select>
          <Input type="file" aria-label="File" className="h-9 max-w-56" onChange={(e) => setFile(e.target.files?.[0] ?? null)} />
          <Button type="submit" size="sm" disabled={!file || upload.isPending}>
            <Upload className="size-4" aria-hidden /> Add
          </Button>
        </form>
      )}
    </Card>
  )
}

export function MessagesPanel({ c }: { c: CaseDetail }) {
  const send = useSendMessage()
  const [confirming, setConfirming] = useState<string | null>(null)
  if (c.messages.length === 0) return null
  return (
    <Card title="Mail" hint="The agents draft; a person holding the purpose's capacity reads and sends each one.">
      <ul className="space-y-3">
        {c.messages.map((m) => (
          <li key={m.id} className="rounded-md border border-border/70 p-2 text-sm">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <span className="font-medium">{m.subject}</span>
              <span className="rounded-full bg-muted px-2 py-0.5 text-xs">{m.status.replace("_", " ")}</span>
            </div>
            <p className="text-xs text-muted-foreground">
              {m.direction === "inbound" ? "From" : "To"} {m.to_email} · {m.purpose.replace(/_/g, " ")}
            </p>
            <pre className="mt-1 max-h-40 overflow-auto whitespace-pre-wrap font-sans text-xs text-foreground/80">{m.body}</pre>
            {m.status === "draft" &&
              (confirming === m.id ? (
                <div className="mt-2 space-y-2 rounded bg-muted/50 p-2 text-xs">
                  <p>Sending approves this exact message: the recipient, the content and the tone.</p>
                  <div className="flex gap-2">
                    <Button size="sm" disabled={send.isPending}
                      onClick={() => send.mutate({ id: m.id, version: m.version }, {
                        onSuccess: () => { toast.success("Sent"); setConfirming(null) },
                        onError: (e) => fail(e, "Couldn't send"),
                      })}>
                      {send.isPending ? <LoaderCircle className="size-4 animate-spin" aria-hidden /> : <Send className="size-4" aria-hidden />}
                      Approve and send
                    </Button>
                    <Button size="sm" variant="ghost" onClick={() => setConfirming(null)}>Cancel</Button>
                  </div>
                </div>
              ) : (
                <Button size="sm" variant="outline" className="mt-2" onClick={() => setConfirming(m.id)}>
                  Review and send…
                </Button>
              ))}
          </li>
        ))}
      </ul>
    </Card>
  )
}

export function PostingsPanel({ c }: { c: CaseDetail }) {
  const act = useTaskAction()
  const sources = useSources(c.workflow)
  const [snapshot, setSnapshot] = useState("")
  if (c.posting_tasks.length === 0) return null
  const fresh = (sources.data ?? []).filter((s) => s.id !== c.snapshot_id)
  return (
    <Card title="ERPNext postings" hint="Posted by the app once approved; verified only by a later snapshot that contains them.">
      <ul className="space-y-3 text-sm">
        {c.posting_tasks.map((t) => (
          <li key={t.id} className="rounded-md border border-border/70 p-2">
            <div className="flex items-center justify-between gap-2">
              <span className="font-medium">{t.kind.replace(/_/g, " ")} · {t.reference}</span>
              <span className="rounded-full bg-muted px-2 py-0.5 text-xs">{t.status.replace("_", " ")}</span>
            </div>
            {t.external_txn_id && <p className="text-xs text-muted-foreground">ERPNext: {t.external_txn_id}</p>}
            {t.kind === "create_journal_entry" && <JournalLines doc={t.instructions.doc} />}
            <div className="mt-2 flex flex-wrap gap-2">
              {t.allowed_actions.post === null && (
                <Button size="sm" disabled={act.isPending}
                  onClick={() => act.mutate({ id: t.id, version: t.version, action: "post" }, {
                    onSuccess: () => toast.success("Posted to ERPNext"), onError: (e) => fail(e, "Posting failed"),
                  })}>
                  Post to ERPNext
                </Button>
              )}
              {t.allowed_actions.verify === null && (
                <>
                  <select aria-label="Fresh snapshot" className={cn(selectClass, "h-9 w-64")} value={snapshot}
                    onChange={(e) => setSnapshot(e.target.value)}>
                    <option value="">Choose a fresh snapshot…</option>
                    {fresh.map((s) => (
                      <option key={s.id} value={s.id}>
                        {s.company_name} · {new Date(s.imported_at).toLocaleString()}
                      </option>
                    ))}
                  </select>
                  <Button size="sm" variant="outline" disabled={!snapshot || act.isPending}
                    onClick={() => act.mutate({ id: t.id, version: t.version, action: "verify", snapshotId: snapshot }, {
                      onSuccess: () => toast.success("Verified"), onError: (e) => fail(e, "Not verified"),
                    })}>
                    Verify
                  </Button>
                </>
              )}
            </div>
          </li>
        ))}
      </ul>
    </Card>
  )
}

interface JournalRow {
  account: string
  debit_in_account_currency: string
  credit_in_account_currency: string
  cost_center?: string
}

/** The journal a close proposes, as it will be posted: date, then each account's side. */
function JournalLines({ doc }: { doc: unknown }) {
  const journal = doc as { posting_date?: string; accounts?: JournalRow[] } | undefined
  if (!journal?.accounts) return null
  return (
    <div className="mt-2 overflow-x-auto">
      <p className="text-xs text-muted-foreground">Posting date {journal.posting_date}</p>
      <table className="mt-1 w-full text-xs">
        <thead className="text-left text-muted-foreground">
          <tr><th className="font-normal">Account</th><th className="text-right font-normal">Debit</th><th className="text-right font-normal">Credit</th></tr>
        </thead>
        <tbody>
          {journal.accounts.map((r, i) => (
            <tr key={i} className="tabular-nums">
              <td>{r.account}{r.cost_center ? ` · ${r.cost_center}` : ""}</td>
              <td className="text-right">{Number(r.debit_in_account_currency) ? r.debit_in_account_currency : ""}</td>
              <td className="text-right">{Number(r.credit_in_account_currency) ? r.credit_in_account_currency : ""}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

/** The workflow's own actions beside the steps (the guard says who may, and when). */
export function ActionsPanel({ c }: { c: CaseDetail }) {
  const act = useCaseAction()
  const sources = useSources(c.workflow)
  const [open, setOpen] = useState<string | null>(null)
  const [form, setForm] = useState<Record<string, string>>({})
  const set = (k: string, v: string) => setForm((f) => ({ ...f, [k]: v }))
  const allowed = (name: string) => name in c.allowed_actions && c.allowed_actions[name] === null
  const run = (action: string, payload: Record<string, unknown>, done: string) =>
    act.mutate(
      { id: c.id, version: c.version, action, payload },
      { onSuccess: () => { toast.success(done); setOpen(null); setForm({}) }, onError: (e) => fail(e, "That didn't work") },
    )
  const newer = (sources.data ?? []).filter((s) => s.id !== c.snapshot_id)
  const quotes = c.artifacts.filter((a) => a.kind === "quote")
  const actions = [
    allowed("record_quote") && "record_quote",
    allowed("log_acknowledgement") && "log_acknowledgement",
    allowed("enter_vendor_details") && "enter_vendor_details",
    allowed("refresh_source") && newer.length > 0 && "refresh_source",
    allowed("complete") && "complete",
  ].filter(Boolean) as string[]
  if (actions.length === 0) return null
  const LABELS: Record<string, string> = {
    record_quote: "Record a quote",
    log_acknowledgement: "Log the vendor's acknowledgement",
    enter_vendor_details: "Enter document details by hand",
    refresh_source: "Move to a fresh snapshot",
    complete: "Complete the case",
  }
  return (
    <Card title="Actions">
      <div className="flex flex-wrap gap-2">
        {actions.map((a) =>
          a === "complete" ? (
            <Button key={a} size="sm" onClick={() => run("complete", {}, "Completed")}>{LABELS[a]}</Button>
          ) : (
            <Button key={a} size="sm" variant={open === a ? "secondary" : "outline"} onClick={() => setOpen(open === a ? null : a)}>
              {LABELS[a]}
            </Button>
          ),
        )}
      </div>
      {open === "record_quote" && (
        <form className="mt-3 grid gap-2 sm:grid-cols-2" onSubmit={(e) => {
          e.preventDefault()
          run("record_quote", {
            vendor_name: form.vendor_name, vendor_id: form.vendor_id || null, reference: form.reference,
            total: form.total, lead_time_days: form.lead ? Number(form.lead) : null, terms: form.terms || null,
            document_id: form.document_id, rates: form.item && form.rate ? { [form.item]: form.rate } : {},
          }, "Quote recorded")
        }}>
          <Input placeholder="Vendor name" value={form.vendor_name ?? ""} onChange={(e) => set("vendor_name", e.target.value)} required />
          <Input placeholder="Vendor id (if in the master)" value={form.vendor_id ?? ""} onChange={(e) => set("vendor_id", e.target.value)} />
          <Input placeholder="Quote reference" value={form.reference ?? ""} onChange={(e) => set("reference", e.target.value)} required />
          <Input placeholder="Total" type="number" step="0.01" value={form.total ?? ""} onChange={(e) => set("total", e.target.value)} required />
          <Input placeholder="Lead time (days)" type="number" value={form.lead ?? ""} onChange={(e) => set("lead", e.target.value)} />
          <Input placeholder="Terms" value={form.terms ?? ""} onChange={(e) => set("terms", e.target.value)} />
          <Input placeholder="Item code (for its unit rate)" value={form.item ?? ""} onChange={(e) => set("item", e.target.value)} />
          <Input placeholder="Unit rate" type="number" step="any" value={form.rate ?? ""} onChange={(e) => set("rate", e.target.value)} />
          <select className={selectClass} value={form.document_id ?? ""} onChange={(e) => set("document_id", e.target.value)} required>
            <option value="">The quote document…</option>
            {quotes.map((q) => <option key={q.id} value={q.id}>{q.filename}</option>)}
          </select>
          <Button type="submit" size="sm" disabled={act.isPending}>Record</Button>
        </form>
      )}
      {open === "log_acknowledgement" && (
        <form className="mt-3 flex flex-wrap gap-2" onSubmit={(e) => {
          e.preventDefault()
          run("log_acknowledgement", { how: form.how || "reply", note: form.note }, "Acknowledgement logged")
        }}>
          <select className={cn(selectClass, "w-40")} value={form.how ?? "reply"} onChange={(e) => set("how", e.target.value)}>
            {["reply", "phone", "vendor_portal", "other"].map((h) => <option key={h} value={h}>{h.replace("_", " ")}</option>)}
          </select>
          <Input className="max-w-md" placeholder="What the vendor said" value={form.note ?? ""} onChange={(e) => set("note", e.target.value)} required />
          <Button type="submit" size="sm" disabled={act.isPending}>Log</Button>
        </form>
      )}
      {open === "enter_vendor_details" && (
        <form className="mt-3 grid gap-2 sm:grid-cols-2" onSubmit={(e) => {
          e.preventDefault()
          run("enter_vendor_details", {
            tax_document_id: form.tax_doc, bank_document_id: form.bank_doc, legal_name: form.legal_name,
            tax_form: form.tax_form || "W-9", tax_id: form.tax_id || null, bank_name: form.bank_name,
            account_holder: form.holder, account_number: form.account, routing_number: form.routing || null, iban: form.iban || null,
          }, "Details entered")
        }}>
          {(["tax_form", "bank_letter"] as const).map((k) => (
            <select key={k} className={selectClass} value={form[k === "tax_form" ? "tax_doc" : "bank_doc"] ?? ""} required
              onChange={(e) => set(k === "tax_form" ? "tax_doc" : "bank_doc", e.target.value)}>
              <option value="">{ARTIFACT_KIND[k]} (from the portal)…</option>
              {c.artifacts.filter((a) => a.kind === k && a.channel === "vendor_portal").map((a) => (
                <option key={a.id} value={a.id}>{a.filename}</option>
              ))}
            </select>
          ))}
          <Input placeholder="Legal name" value={form.legal_name ?? ""} onChange={(e) => set("legal_name", e.target.value)} required />
          <select className={selectClass} value={form.tax_form ?? "W-9"} onChange={(e) => set("tax_form", e.target.value)}>
            {["W-9", "W-8BEN", "W-8BEN-E"].map((f) => <option key={f}>{f}</option>)}
          </select>
          <Input placeholder="Tax ID (e.g. 84-1234567)" value={form.tax_id ?? ""} onChange={(e) => set("tax_id", e.target.value)} />
          <Input placeholder="Bank name" value={form.bank_name ?? ""} onChange={(e) => set("bank_name", e.target.value)} required />
          <Input placeholder="Account holder" value={form.holder ?? ""} onChange={(e) => set("holder", e.target.value)} required />
          <Input placeholder="Account number" value={form.account ?? ""} onChange={(e) => set("account", e.target.value)} required />
          <Input placeholder="Routing number (9 digits)" value={form.routing ?? ""} onChange={(e) => set("routing", e.target.value)} />
          <Input placeholder="IBAN" value={form.iban ?? ""} onChange={(e) => set("iban", e.target.value)} />
          <Button type="submit" size="sm" disabled={act.isPending}>Save</Button>
        </form>
      )}
      {open === "refresh_source" && (
        <form className="mt-3 flex flex-wrap gap-2" onSubmit={(e) => {
          e.preventDefault()
          run("refresh_source", { snapshot_id: form.snapshot }, "Moved to the fresh snapshot")
        }}>
          <select className={cn(selectClass, "w-72")} value={form.snapshot ?? ""} onChange={(e) => set("snapshot", e.target.value)} required>
            <option value="">A newer snapshot…</option>
            {newer.map((s) => <option key={s.id} value={s.id}>{s.company_name} · {new Date(s.imported_at).toLocaleString()}</option>)}
          </select>
          <Button type="submit" size="sm" disabled={act.isPending}>Move</Button>
        </form>
      )}
    </Card>
  )
}
