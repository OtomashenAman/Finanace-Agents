import { useRef, useState } from "react"
import { Link, useNavigate, useSearchParams } from "react-router"
import { FileUp, Keyboard, LoaderCircle, Sparkles, Trash2 } from "lucide-react"
import { toast } from "sonner"

import { Button } from "@/components/ui/button"
import { AiBadge, AiCard, Card, Empty, LoadError, Loading, Pill } from "@/features/service-pod/components/bits"
import { attempt } from "@/features/service-pod/ui"
import { errorMessage } from "@/lib/api"
import { cn } from "@/lib/utils"

import { FpodPage } from "./components/fpod-page"
import { useFpodMutation, useInvoiceMeasures, useInvoices } from "./hooks"
import { invoicesApi, type InvoiceStatus } from "./invoices-api"
import { formatDate, INVOICE_STATUS, money } from "./labels"

function Kpis() {
  const m = useInvoiceMeasures()
  if (!m.data) return null
  const d = m.data
  const tiles = [
    { label: "First-pass match rate", value: d.first_pass_rate === null ? "—" : `${Math.round(d.first_pass_rate * 100)}%`,
      hint: `${d.first_pass_matched} of ${d.first_pass_judged} matched without help` },
    { label: "Open exceptions", value: String(d.exceptions_open),
      hint: d.oldest_open_days !== null ? `oldest ${d.oldest_open_days} days` : "none waiting" },
    { label: "Duplicates stopped", value: String(d.duplicates_stopped), hint: `${money(d.duplicates_amount)} not paid twice` },
    { label: "Ready for coding", value: String(d.ready_for_coding), hint: "matched or resolved" },
  ]
  return (
    <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
      {tiles.map((t) => (
        <div key={t.label} className="rounded-xl border border-border/80 bg-card p-4">
          <p className="text-xs text-muted-foreground">{t.label}</p>
          <p className="mt-1 text-3xl font-semibold tabular-nums">{t.value}</p>
          <p className="mt-1 text-xs text-muted-foreground">{t.hint}</p>
        </div>
      ))}
    </div>
  )
}

function Capture() {
  const navigate = useNavigate()
  const capture = useFpodMutation(invoicesApi.capture)
  const input = useRef<HTMLInputElement>(null)
  const [over, setOver] = useState(false)
  const run = async (file: File | undefined) => {
    if (!file) return
    try {
      const inv = await capture.mutateAsync([file])
      toast.success(inv.extraction?.error ? "Uploaded; the agent couldn't read it all: fill in the rest." : `The capture agent read ${inv.reference}. Check it, then post.`)
      navigate(`/finance-pod/invoices/${inv.id}`)
    } catch (error) {
      toast.error(errorMessage(error, "The invoice couldn't be uploaded."))
    }
  }
  return (
    <AiCard
      title="Capture an invoice"
      hint="the capture agent reads the vendor, number, dates, PO and lines. Figures read from a document's text must be in it; from a scan you confirm them."
      badge={<AiBadge label="Capture agent" />}
    >
      <div
        onDragOver={(e) => {
          e.preventDefault()
          setOver(true)
        }}
        onDragLeave={() => setOver(false)}
        onDrop={(e) => {
          e.preventDefault()
          setOver(false)
          void run(e.dataTransfer.files?.[0])
        }}
        className={cn(
          "flex flex-col items-center justify-center gap-2 rounded-xl border-2 border-dashed px-4 py-8 text-center transition-colors",
          over ? "border-primary bg-primary/5" : "border-border bg-muted/20",
        )}
      >
        {capture.isPending ? (
          <>
            <LoaderCircle className="size-6 animate-spin text-primary" aria-hidden />
            <p className="text-sm">The capture agent is reading the invoice…</p>
          </>
        ) : (
          <>
            <FileUp className="size-7 text-muted-foreground" aria-hidden />
            <p className="text-sm">Drop the invoice here (PDF, PNG, JPEG or TXT)</p>
            <div className="flex gap-2">
              <input
                ref={input}
                type="file"
                className="hidden"
                accept=".pdf,.png,.jpg,.jpeg,.txt"
                onChange={(e) => {
                  const f = e.target.files?.[0]
                  e.target.value = ""
                  void run(f)
                }}
              />
              <Button size="sm" onClick={() => input.current?.click()}>
                <Sparkles aria-hidden /> Choose file
              </Button>
              <Button size="sm" variant="outline" asChild>
                <Link to="/finance-pod/invoices/new">
                  <Keyboard aria-hidden /> Key it by hand
                </Link>
              </Button>
            </div>
          </>
        )}
      </div>
    </AiCard>
  )
}

const FILTERS: (InvoiceStatus | null)[] = [null, "captured", "duplicate", "exception", "ready", "paid", "rejected"]

export function InvoicesPage() {
  const [params, setParams] = useSearchParams()
  const status = (params.get("status") as InvoiceStatus | null) || null
  const list = useInvoices(status)
  const remove = useFpodMutation(invoicesApi.remove)
  const [picked, setPicked] = useState<string[]>([])
  const shown = list.data ?? []
  const pickedShown = picked.filter((id) => shown.some((i) => i.id === id))
  const allPicked = shown.length > 0 && pickedShown.length === shown.length
  const del = async (ids: string[], what: string) => {
    if (!window.confirm(`Delete ${what}? Its exception goes too; the audit trail keeps a record.`)) return
    const ok = await attempt(() => remove.mutateAsync([ids]), (r) => `Deleted ${r.deleted} invoice${r.deleted === 1 ? "" : "s"}.`)
    if (ok) setPicked((p) => p.filter((id) => !ids.includes(id)))
  }
  return (
    <FpodPage
      title="Invoices"
      subtitle="Posting, duplicate guard and three-way match by agents; buyers and receivers step in only on exceptions."
    >
      <div className="space-y-5">
        <Kpis />
        <Capture />
        <Card
          title="Invoices"
          actions={
            <div className="flex flex-wrap gap-1">
              {FILTERS.map((f) => (
                <button
                  key={f ?? "all"}
                  type="button"
                  onClick={() => setParams(f ? { status: f } : {}, { replace: true })}
                  className={cn(
                    "rounded-full border px-2.5 py-0.5 text-xs",
                    status === f ? "border-primary bg-primary text-primary-foreground" : "border-border hover:bg-muted",
                  )}
                >
                  {f ? INVOICE_STATUS[f][0] : "All"}
                </button>
              ))}
            </div>
          }
        >
          {list.isPending ? (
            <Loading what="invoices" />
          ) : list.isError ? (
            <LoadError what="invoices" />
          ) : list.data.length === 0 ? (
            <Empty>No invoices{status ? " with this status" : " yet: capture one above"}.</Empty>
          ) : (
            <div className="overflow-x-auto">
              {pickedShown.length > 0 && (
                <div className="mb-2 flex items-center justify-between gap-2 rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-900">
                  <span>
                    {pickedShown.length} selected
                  </span>
                  <span className="flex gap-2">
                    <Button size="sm" variant="ghost" onClick={() => setPicked([])}>
                      Clear
                    </Button>
                    <Button
                      size="sm"
                      variant="destructive"
                      disabled={remove.isPending}
                      onClick={() => void del(pickedShown, `${pickedShown.length} invoice${pickedShown.length === 1 ? "" : "s"}`)}
                    >
                      <Trash2 aria-hidden /> Delete selected
                    </Button>
                  </span>
                </div>
              )}
              <table className="w-full text-sm">
                <thead className="text-left text-xs text-muted-foreground">
                  <tr className="border-b border-border">
                    <th className="w-8 py-2">
                      <input
                        type="checkbox"
                        aria-label="Select all"
                        checked={allPicked}
                        onChange={(e) => setPicked(e.target.checked ? shown.map((i) => i.id) : [])}
                      />
                    </th>
                    <th className="py-2 pr-3 font-medium">Invoice</th>
                    <th className="py-2 pr-3 font-medium">Vendor</th>
                    <th className="py-2 pr-3 font-medium">PO</th>
                    <th className="py-2 pr-3 font-medium">Date</th>
                    <th className="py-2 pr-3 font-medium">Status</th>
                    <th className="py-2 pr-3 font-medium">First pass</th>
                    <th className="py-2 pr-3 text-right font-medium">Total</th>
                    <th className="w-10" />
                  </tr>
                </thead>
                <tbody>
                  {list.data.map((i) => (
                    <tr key={i.id} className={cn("border-b border-border/60 hover:bg-muted/30", picked.includes(i.id) && "bg-red-50/50")}>
                      <td className="py-2">
                        <input
                          type="checkbox"
                          aria-label={`Select ${i.reference}`}
                          checked={picked.includes(i.id)}
                          onChange={(e) => setPicked((p) => (e.target.checked ? [...p, i.id] : p.filter((x) => x !== i.id)))}
                        />
                      </td>
                      <td className="py-2 pr-3">
                        <Link to={`/finance-pod/invoices/${i.id}`} className="font-medium text-primary hover:underline">
                          {i.reference}
                        </Link>
                        <span className="block text-xs text-muted-foreground">{i.vendor_invoice_number ?? "number ?"}</span>
                      </td>
                      <td className="py-2 pr-3">{i.vendor_name ?? "—"}</td>
                      <td className="py-2 pr-3">{i.po_reference ?? "—"}</td>
                      <td className="py-2 pr-3">{formatDate(i.invoice_date)}</td>
                      <td className="py-2 pr-3">
                        <Pill label={INVOICE_STATUS[i.status][0]} tone={INVOICE_STATUS[i.status][1]} />
                      </td>
                      <td className="py-2 pr-3">
                        {i.first_pass_matched === null ? "—" : i.first_pass_matched ? <Pill label="Matched" tone="good" /> : <Pill label="Exception" tone="warn" />}
                      </td>
                      <td className="py-2 pr-3 text-right tabular-nums">{money(i.total, i.currency)}</td>
                      <td className="py-2">
                        <Button
                          size="icon"
                          variant="ghost"
                          aria-label={`Delete ${i.reference}`}
                          title="Delete"
                          disabled={remove.isPending}
                          onClick={() => void del([i.id], i.reference)}
                        >
                          <Trash2 aria-hidden className="text-muted-foreground" />
                        </Button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </Card>
      </div>
    </FpodPage>
  )
}
