import { useRef, useState } from "react"
import { Link, useNavigate } from "react-router"
import { FlaskConical, Plus, Send, Trash2, Upload } from "lucide-react"
import { toast } from "sonner"

import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Card, Empty, Field, LoadError, Loading, Pill } from "@/features/service-pod/components/bits"
import { formatDateTime } from "@/features/service-pod/labels"
import { attempt, selectClass } from "@/features/service-pod/ui"
import { errorMessage } from "@/lib/api"
import { cn } from "@/lib/utils"

import { billingApi, type PerformedIn, type Submission, type SubmissionLineIn, type SubmissionStatus, type Turnaround } from "./billing-api"
import { FpodPage } from "./components/fpod-page"
import { useClients, useFeeSchedule, useFpodMutation, useSubmissions } from "./hooks"
import { formatDate, money, SUBMISSION_STATUS } from "./labels"

const BLANK: SubmissionLineIn = { item_ref: "", stone_type: "diamond", carat: null, service_code: "", quantity: 1, special_price: null, special_reason: null }

function Receive() {
  const clients = useClients().data ?? []
  const codes = [...new Set((useFeeSchedule().data?.fees ?? []).map((f) => f.service_code))]
  const create = useFpodMutation(billingApi.createSubmission)
  const imp = useFpodMutation(billingApi.importSubmissions)
  const input = useRef<HTMLInputElement>(null)
  const [client, setClient] = useState("")
  const [turnaround, setTurnaround] = useState<Turnaround>("standard")
  const [estimate, setEstimate] = useState("")
  const [lines, setLines] = useState<SubmissionLineIn[]>([{ ...BLANK, item_ref: "1" }])
  const set = (i: number, patch: Partial<SubmissionLineIn>) => setLines((ls) => ls.map((l, j) => (j === i ? { ...l, ...patch } : l)))
  const ready = client && lines.every((l) => l.item_ref.trim() && l.service_code.trim() && l.stone_type.trim())
  return (
    <Card
      title="Receive a submission"
      hint="What the lab system records at intake. Once a lab system is connected it sends these itself (POST /api/v1/lab-events)."
      actions={
        <>
          <Input
            ref={input}
            type="file"
            accept=".csv,.xlsx"
            className="hidden"
            onChange={async (e) => {
              const file = e.target.files?.[0]
              e.target.value = ""
              if (file)
                await attempt(
                  () => imp.mutateAsync([file]),
                  (r) => `${r.submissions} submission(s) imported, ${r.issued} invoiced${r.errors.length ? `; ${r.errors.length} with problems: ${r.errors.join("; ")}` : ""}.`,
                )
            }}
          />
          <Button
            size="sm"
            variant="outline"
            disabled={imp.isPending}
            onClick={() => input.current?.click()}
            title="One row per service: Submission, Client, Turnaround, Received, Estimate, Item, Stone, Carat, Service, Qty, Special Price, Special Reason, Report Issued, Performed"
          >
            <Upload aria-hidden /> Import from the lab system
          </Button>
        </>
      }
    >
      <datalist id="fpod-services">
        {codes.map((c) => (
          <option key={c} value={c} />
        ))}
      </datalist>
      <div className="grid gap-3 sm:grid-cols-3">
        <Field label="Client account">
          <select className={selectClass} value={client} onChange={(e) => setClient(e.target.value)}>
            <option value="">Choose…</option>
            {clients.map((c) => (
              <option key={c.code} value={c.code}>
                {c.code} {c.name}
              </option>
            ))}
          </select>
        </Field>
        <Field label="Turnaround">
          <select className={selectClass} value={turnaround} onChange={(e) => setTurnaround(e.target.value as Turnaround)}>
            <option value="standard">Standard</option>
            <option value="express">Express</option>
            <option value="rush">Rush</option>
          </select>
        </Field>
        <Field label="Fee estimate given to the client">
          <Input inputMode="decimal" value={estimate} onChange={(e) => setEstimate(e.target.value)} />
        </Field>
      </div>
      <div className="mt-3 space-y-2">
        {lines.map((l, i) => (
          <div key={i} className="grid gap-2 rounded-lg border border-border/70 p-2 sm:grid-cols-[0.6fr_1fr_0.7fr_0.9fr_0.5fr_0.8fr_1.4fr_auto]">
            <Input aria-label="Item" placeholder="Item" value={l.item_ref} onChange={(e) => set(i, { item_ref: e.target.value })} />
            <select aria-label="Stone type" className={selectClass} value={l.stone_type} onChange={(e) => set(i, { stone_type: e.target.value })}>
              <option value="diamond">Diamond</option>
              <option value="coloured">Coloured stone</option>
              <option value="pearl">Pearl</option>
              <option value="other">Other</option>
            </select>
            <Input aria-label="Carat" placeholder="Carat" inputMode="decimal" value={l.carat ?? ""} onChange={(e) => set(i, { carat: e.target.value || null })} />
            <Input aria-label="Service code" placeholder="Service" list="fpod-services" value={l.service_code} onChange={(e) => set(i, { service_code: e.target.value.toUpperCase() })} />
            <Input aria-label="Quantity" type="number" min={1} value={l.quantity} onChange={(e) => set(i, { quantity: Number(e.target.value) || 1 })} />
            <Input aria-label="Special price" placeholder="Special price" inputMode="decimal" value={l.special_price ?? ""} onChange={(e) => set(i, { special_price: e.target.value || null })} />
            <Input aria-label="Why the special price" placeholder="Why (client services)" value={l.special_reason ?? ""} onChange={(e) => set(i, { special_reason: e.target.value || null })} />
            <Button size="icon" variant="ghost" aria-label="Remove line" disabled={lines.length === 1} onClick={() => setLines((ls) => ls.filter((_, j) => j !== i))}>
              <Trash2 aria-hidden />
            </Button>
          </div>
        ))}
        <div className="flex flex-wrap gap-2">
          <Button size="sm" variant="outline" onClick={() => setLines((ls) => [...ls, { ...BLANK, item_ref: String(ls.length + 1) }])}>
            <Plus aria-hidden /> Add a service
          </Button>
          <Button
            size="sm"
            disabled={create.isPending || !ready}
            onClick={async () => {
              const s = await attempt(
                () => create.mutateAsync([{ client_code: client, turnaround, estimate: estimate || null, notes: null, lines }]),
                (r) => `${r.reference} received.`,
              )
              if (s) {
                setLines([{ ...BLANK, item_ref: "1" }])
                setEstimate("")
              }
            }}
          >
            Record submission
          </Button>
        </div>
      </div>
    </Card>
  )
}

function IssueReport({ s, onDone }: { s: Submission; onDone: () => void }) {
  const navigate = useNavigate()
  const issue = useFpodMutation(billingApi.reportIssued)
  const [done, setDone] = useState<Record<string, boolean>>(Object.fromEntries(s.lines.map((l) => [l.id, true])))
  const [added, setAdded] = useState<PerformedIn[]>([])
  return (
    <div className="mt-2 space-y-2 rounded-lg border border-primary/30 bg-primary/5 p-3 text-sm">
      <p className="font-medium">Which services did the lab perform?</p>
      {s.lines.map((l) => (
        <label key={l.id} className="flex items-center gap-2">
          <input type="checkbox" checked={done[l.id]} onChange={(e) => setDone({ ...done, [l.id]: e.target.checked })} />
          {l.item_ref} · {l.service_code} · {l.stone_type}
          {l.carat && ` ${l.carat} ct`}
        </label>
      ))}
      {added.map((a, i) => (
        <div key={i} className="flex gap-2">
          <Input className="h-8 w-24" placeholder="Item" value={a.item_ref} onChange={(e) => setAdded(added.map((x, j) => (j === i ? { ...x, item_ref: e.target.value } : x)))} />
          <Input className="h-8 w-32" placeholder="Service" list="fpod-services" value={a.service_code} onChange={(e) => setAdded(added.map((x, j) => (j === i ? { ...x, service_code: e.target.value.toUpperCase() } : x)))} />
          <span className="self-center text-xs text-amber-800">added in the lab</span>
        </div>
      ))}
      <div className="flex flex-wrap gap-2">
        <Button size="sm" variant="ghost" onClick={() => setAdded([...added, { item_ref: s.lines[0]?.item_ref ?? "", service_code: "" }])}>
          <Plus aria-hidden /> A service the lab added
        </Button>
        <Button
          size="sm"
          disabled={issue.isPending}
          onClick={async () => {
            const performed: PerformedIn[] = [
              ...s.lines.filter((l) => done[l.id]).map((l) => ({ item_ref: l.item_ref, service_code: l.service_code, quantity: l.quantity })),
              ...added.filter((a) => a.item_ref.trim() && a.service_code.trim()),
            ]
            try {
              const inv = await issue.mutateAsync([s.id, performed])
              toast.success(
                inv.status === "sent"
                  ? `${inv.reference} built, priced and sent to the client.`
                  : `${inv.reference} built: ${inv.open_items.length} item(s) for the billing analyst.`,
              )
              onDone()
              navigate(`/finance-pod/billing/${inv.id}`)
            } catch (error) {
              toast.error(errorMessage(error, "The report couldn't be marked issued."))
            }
          }}
        >
          <Send aria-hidden /> Report issued: build the invoice
        </Button>
      </div>
    </div>
  )
}

export function LabSubmissionsPage() {
  const [status, setStatus] = useState<SubmissionStatus | null>(null)
  const [open, setOpen] = useState<string | null>(null)
  const list = useSubmissions(status)
  return (
    <FpodPage title="Lab submissions" subtitle="When the lab issues a report, the billing agent builds the invoice from the services actually performed.">
      <div className="space-y-5">
        <Receive />
        <Card
          title="Submissions"
          actions={
            <div className="flex flex-wrap rounded-lg border border-border p-0.5 text-xs">
              {([null, "in_lab", "report_issued", "invoiced"] as (SubmissionStatus | null)[]).map((k) => (
                <button
                  key={k ?? "all"}
                  type="button"
                  onClick={() => setStatus(k)}
                  className={cn("rounded-md px-2.5 py-1 font-medium", status === k ? "bg-primary text-primary-foreground" : "text-muted-foreground")}
                >
                  {k ? SUBMISSION_STATUS[k][0] : "All"}
                </button>
              ))}
            </div>
          }
        >
          {list.isPending ? (
            <Loading what="submissions" />
          ) : list.isError ? (
            <LoadError what="submissions" />
          ) : list.data.length === 0 ? (
            <Empty icon={<FlaskConical className="size-5" />}>No submissions.</Empty>
          ) : (
            <ul className="divide-y divide-border/60 text-sm">
              {list.data.map((s) => (
                <li key={s.id} className="py-2.5">
                  <div className="flex flex-wrap items-center justify-between gap-2">
                    <span>
                      <span className="font-medium">{s.reference}</span>
                      {s.external_ref && <span className="text-xs text-muted-foreground"> · lab {s.external_ref}</span>}
                      <span className="block text-xs text-muted-foreground">
                        {s.client_code} {s.client_name} · received {formatDate(s.received_on)} · {s.turnaround} · {s.lines.length} service(s)
                        {s.estimate && ` · estimate ${money(s.estimate)}`}
                        {s.report_issued_at && ` · report issued ${formatDateTime(s.report_issued_at)} (${s.issued_via})`}
                      </span>
                    </span>
                    <span className="flex items-center gap-2">
                      {s.invoice_id && (
                        <Link to={`/finance-pod/billing/${s.invoice_id}`} className="text-xs font-medium text-primary hover:underline">
                          {s.invoice_reference}
                        </Link>
                      )}
                      <Pill label={SUBMISSION_STATUS[s.status][0]} tone={SUBMISSION_STATUS[s.status][1]} />
                      {s.status === "in_lab" && (
                        <Button size="sm" variant={open === s.id ? "ghost" : "outline"} onClick={() => setOpen(open === s.id ? null : s.id)}>
                          {open === s.id ? "Close" : "Report issued…"}
                        </Button>
                      )}
                    </span>
                  </div>
                  {open === s.id && <IssueReport s={s} onDone={() => setOpen(null)} />}
                </li>
              ))}
            </ul>
          )}
        </Card>
      </div>
    </FpodPage>
  )
}
