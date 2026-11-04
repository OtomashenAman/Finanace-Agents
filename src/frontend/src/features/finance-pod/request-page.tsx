import { useRef, useState } from "react"
import { Link, useParams } from "react-router"
import { Bot, CircleAlert, CircleCheck, Download, Pencil, Send, Sparkles, Trash2, Upload, XCircle } from "lucide-react"

import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { AiBadge, AiCard, Card, Empty, GuardedButton, LoadError, Loading, Pill } from "@/features/service-pod/components/bits"
import { useCurrentUser } from "@/features/auth/hooks"
import { attempt, selectClass } from "@/features/service-pod/ui"
import { formatDateTime } from "@/features/service-pod/labels"

import { fpodApi, type PurchaseRequest, type Reference, type RequestFileKind } from "./api"
import { BudgetCheckCard, DecisionCard, DecisionHistory } from "./components/budget-panel"
import { PoPanel } from "./components/po-panel"
import { SourcingPanel } from "./components/sourcing-panel"
import { FpodPage } from "./components/fpod-page"
import { RequestForm } from "./components/request-form"
import { fromRequest } from "./request-draft"
import { useFpodMutation, useReference, useRequest } from "./hooks"
import { FILE_KIND, formatDate, money, PRICE_STATUS, REQUEST_STATUS } from "./labels"

function name(reference: Reference | undefined, kind: "cost_centres" | "labs" | "projects" | "grants", code: string | null) {
  if (!code) return "—"
  const row = reference?.[kind].find((r) => r.code === code)
  return row ? `${code} · ${row.name}` : code
}

function Facts({ r, reference }: { r: PurchaseRequest; reference: Reference | undefined }) {
  const rows: [string, string][] = [
    ["Requester", r.requester_name],
    ["Needed by", formatDate(r.needed_by)],
    ["Cost centre", name(reference, "cost_centres", r.cost_centre_code)],
    ["Lab", name(reference, "labs", r.lab_code)],
    ["Project", name(reference, "projects", r.project_code)],
    ["Grant", name(reference, "grants", r.grant_code)],
    ["Coding by", r.coding_source === "agent" ? "Request agent (accepted)" : r.coding_source === "requester" ? "Requester" : "—"],
    ["Submitted", r.submitted_at ? formatDateTime(r.submitted_at) : "—"],
  ]
  return (
    <dl className="grid gap-x-6 gap-y-2 text-sm sm:grid-cols-2">
      {rows.map(([k, v]) => (
        <div key={k} className="flex justify-between gap-3 border-b border-border/50 pb-1">
          <dt className="text-muted-foreground">{k}</dt>
          <dd className="text-right font-medium">{v}</dd>
        </div>
      ))}
      <div className="sm:col-span-2">
        <dt className="text-muted-foreground">Purpose</dt>
        <dd className="mt-0.5 whitespace-pre-wrap">{r.purpose || "—"}</dd>
      </div>
      {r.source_text && (
        <div className="sm:col-span-2">
          <dt className="text-muted-foreground">Described as</dt>
          <dd className="mt-0.5 whitespace-pre-wrap text-muted-foreground italic">“{r.source_text}”</dd>
        </div>
      )}
    </dl>
  )
}

function Lines({ r }: { r: PurchaseRequest }) {
  const checks = new Map((r.enrichment?.price_checks ?? []).map((c) => [c.line, c]))
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-sm">
        <thead className="text-left text-xs text-muted-foreground">
          <tr className="border-b border-border">
            <th className="py-2 pr-3 font-medium">#</th>
            <th className="py-2 pr-3 font-medium">Description</th>
            <th className="py-2 pr-3 text-right font-medium">Qty</th>
            <th className="py-2 pr-3 text-right font-medium">Unit price</th>
            <th className="py-2 pr-3 font-medium">Category</th>
            <th className="py-2 pr-3 text-right font-medium">Amount</th>
            <th className="py-2 font-medium">Contract price check</th>
          </tr>
        </thead>
        <tbody>
          {r.lines.map((l, i) => {
            const c = checks.get(i + 1)
            return (
              <tr key={i} className="border-b border-border/60 align-top">
                <td className="py-2 pr-3 text-muted-foreground">{i + 1}</td>
                <td className="py-2 pr-3">{l.description}</td>
                <td className="py-2 pr-3 text-right tabular-nums">
                  {Number(l.quantity)} {l.unit ?? ""}
                </td>
                <td className="py-2 pr-3 text-right tabular-nums">{money(l.unit_price)}</td>
                <td className="py-2 pr-3">{l.category ?? "—"}</td>
                <td className="py-2 pr-3 text-right tabular-nums">{money(l.amount)}</td>
                <td className="py-2 text-xs">
                  {c ? (
                    <>
                      <Pill label={PRICE_STATUS[c.status][0]} tone={PRICE_STATUS[c.status][1]} />
                      {c.item_code && (
                        <span className="mt-1 block text-muted-foreground">
                          {c.item_code} at {money(c.contract_price)} from {c.vendor_name ?? c.vendor_code ?? "—"}
                          {c.contract_ref ? ` (${c.contract_ref})` : ""}
                          {c.how === "description" ? ", matched by description" : ""}
                          {c.difference && Number(c.difference) > 0 ? `: ${money(c.difference)} more than contract` : ""}
                        </span>
                      )}
                    </>
                  ) : (
                    "—"
                  )}
                </td>
              </tr>
            )
          })}
        </tbody>
        <tfoot>
          <tr>
            <td colSpan={5} className="py-2 pr-3 text-right font-medium">
              Total
            </td>
            <td className="py-2 pr-3 text-right font-semibold tabular-nums">{money(r.total, r.currency)}</td>
            <td />
          </tr>
        </tfoot>
      </table>
    </div>
  )
}

function RequestAgent({ r, reference }: { r: PurchaseRequest; reference: Reference | undefined }) {
  const suggest = useFpodMutation(fpodApi.suggest)
  const accept = useFpodMutation(fpodApi.acceptSuggestion)
  const e = r.enrichment
  const s = e?.suggestion
  const differs =
    s &&
    (s.cost_centre_code !== r.cost_centre_code ||
      s.lab_code !== r.lab_code ||
      s.project_code !== r.project_code ||
      s.grant_code !== r.grant_code)
  const blocking = e?.problems.filter((p) => p.blocking) ?? []
  const notes = e?.problems.filter((p) => !p.blocking) ?? []
  return (
    <AiCard
      title="Request agent"
      hint="suggests the coding, checks contract prices and flags what's missing before submit. You decide."
      badge={<AiBadge label="AI agent" />}
      actions={
        r.can_edit && (
          <Button
            size="sm"
            variant="outline"
            disabled={suggest.isPending}
            onClick={() => attempt(() => suggest.mutateAsync([r.id]), "The request agent checked the request.")}
          >
            <Sparkles aria-hidden /> {suggest.isPending ? "Thinking…" : s ? "Suggest again" : "Suggest coding"}
          </Button>
        )
      }
    >
      <div className="space-y-4 text-sm">
        <section aria-label="Coding suggestion">
          <h3 className="mb-1 flex items-center gap-1.5 font-semibold">
            <Bot className="size-4 text-violet-600" aria-hidden /> Coding suggestion
          </h3>
          {s ? (
            <div className="rounded-lg border border-violet-200/80 bg-white/60 p-3 dark:bg-transparent">
              <dl className="grid gap-1 sm:grid-cols-2">
                <div>Cost centre: <strong>{name(reference, "cost_centres", s.cost_centre_code)}</strong></div>
                <div>Lab: <strong>{name(reference, "labs", s.lab_code)}</strong></div>
                <div>Project: <strong>{name(reference, "projects", s.project_code)}</strong></div>
                <div>Grant: <strong>{name(reference, "grants", s.grant_code)}</strong></div>
              </dl>
              <p className="mt-2 text-muted-foreground">
                {s.reason}{" "}
                <span className="text-xs">({s.source === "ai" ? "AI, checked against the reference data" : "from your recent requests"})</span>
              </p>
              {r.can_edit && differs && (
                <Button
                  size="sm"
                  className="mt-2"
                  disabled={accept.isPending}
                  onClick={() => attempt(() => accept.mutateAsync([r.id, r.version]), "Coding accepted.")}
                >
                  <CircleCheck aria-hidden /> Accept this coding
                </Button>
              )}
              {!differs && <p className="mt-2 text-xs text-emerald-700">The request uses this coding.</p>}
            </div>
          ) : (
            <p className="text-muted-foreground">
              {e?.suggestion_note ?? "No suggestion yet. Ask the agent to suggest the coding."}
            </p>
          )}
          {s && e?.suggestion_note && <p className="mt-1 text-xs text-muted-foreground">{e.suggestion_note}</p>}
        </section>

        <section aria-label="Before submit">
          <h3 className="mb-1 font-semibold">Before submit</h3>
          {!e ? (
            <p className="text-muted-foreground">Not checked yet.</p>
          ) : blocking.length === 0 && notes.length === 0 ? (
            <p className="flex items-center gap-1.5 text-emerald-700">
              <CircleCheck className="size-4" aria-hidden /> Nothing missing.
            </p>
          ) : (
            <ul className="space-y-1">
              {blocking.map((p) => (
                <li key={p.field + p.message} className="flex items-start gap-1.5 text-red-700 dark:text-red-400">
                  <XCircle className="mt-0.5 size-4 shrink-0" aria-hidden /> {p.message}
                </li>
              ))}
              {notes.map((p) => (
                <li key={p.field + p.message} className="flex items-start gap-1.5 text-amber-800 dark:text-amber-300">
                  <CircleAlert className="mt-0.5 size-4 shrink-0" aria-hidden /> {p.message}
                </li>
              ))}
            </ul>
          )}
          {e && <p className="mt-2 text-xs text-muted-foreground">Checked {formatDateTime(e.ran_at)}</p>}
        </section>
      </div>
    </AiCard>
  )
}

function Files({ r }: { r: PurchaseRequest }) {
  const upload = useFpodMutation(fpodApi.uploadFile)
  const remove = useFpodMutation(fpodApi.removeFile)
  const [kind, setKind] = useState<RequestFileKind>("quote")
  const input = useRef<HTMLInputElement>(null)
  const quotes = r.files.filter((f) => f.kind === "quote").length
  const needed = r.enrichment?.quotes_needed ?? 0
  return (
    <Card
      title="Quotes and documents"
      hint={
        needed
          ? `At or above the purchasing threshold: sourcing will need ${needed} quotes (${quotes} attached).`
          : "Attach a quote if you have one."
      }
      actions={
        r.can_edit && (
          <div className="flex items-center gap-2">
            <select
              aria-label="Document type"
              className={`${selectClass} h-9 w-auto`}
              value={kind}
              onChange={(e) => setKind(e.target.value as RequestFileKind)}
            >
              {(Object.keys(FILE_KIND) as RequestFileKind[]).map((k) => (
                <option key={k} value={k}>
                  {FILE_KIND[k]}
                </option>
              ))}
            </select>
            <Input
              ref={input}
              type="file"
              className="hidden"
              accept=".pdf,.png,.jpg,.jpeg,.csv,.txt,.xlsx,.docx"
              onChange={async (e) => {
                const file = e.target.files?.[0]
                e.target.value = ""
                if (file) await attempt(() => upload.mutateAsync([r.id, file, kind]), `${FILE_KIND[kind]} attached.`)
              }}
            />
            <Button size="sm" variant="outline" disabled={upload.isPending} onClick={() => input.current?.click()}>
              <Upload aria-hidden /> {upload.isPending ? "Uploading…" : "Attach"}
            </Button>
          </div>
        )
      }
    >
      {r.files.length === 0 ? (
        <Empty>No documents attached.</Empty>
      ) : (
        <ul className="divide-y divide-border/60 text-sm">
          {r.files.map((f) => (
            <li key={f.id} className="flex items-center justify-between gap-2 py-2">
              <span>
                <Pill label={FILE_KIND[f.kind]} tone="info" /> <span className="ml-1">{f.filename}</span>
                <span className="ml-2 text-xs text-muted-foreground">{Math.ceil(f.size / 1024)} KB</span>
              </span>
              <span className="flex gap-1">
                <Button size="icon" variant="ghost" aria-label={`Download ${f.filename}`} onClick={() => fpodApi.downloadFile(r.id, f)}>
                  <Download aria-hidden />
                </Button>
                {r.can_edit && (
                  <Button
                    size="icon"
                    variant="ghost"
                    aria-label={`Remove ${f.filename}`}
                    onClick={() => attempt(() => remove.mutateAsync([r.id, f.id]), "Removed.")}
                  >
                    <Trash2 aria-hidden />
                  </Button>
                )}
              </span>
            </li>
          ))}
        </ul>
      )}
    </Card>
  )
}

function Actions({ r, onEdit }: { r: PurchaseRequest; onEdit: () => void }) {
  const submit = useFpodMutation(fpodApi.submit)
  const cancel = useFpodMutation(fpodApi.cancel)
  const blocking = r.enrichment?.problems.filter((p) => p.blocking).length ?? 0
  const { data: me } = useCurrentUser()
  const open = ["draft", "submitted", "queried"].includes(r.status)
  const mine = me?.id === r.requester_id
  return (
    <div className="flex flex-wrap gap-2">
      {r.can_edit && (
        <>
          <Button size="sm" variant="outline" onClick={onEdit}>
            <Pencil aria-hidden /> Edit
          </Button>
          <GuardedButton
            reason={blocking ? `Fix the ${blocking} item${blocking === 1 ? "" : "s"} the request agent flagged first.` : null}
            disabled={submit.isPending}
            onClick={() =>
              attempt(() => submit.mutateAsync([r.id, r.version]), `${r.reference} submitted for the budget check.`)
            }
          >
            <Send aria-hidden /> {r.status === "queried" ? "Resubmit" : "Submit for budget check"}
          </GuardedButton>
        </>
      )}
      {open && mine && (
        <Button
          size="sm"
          variant="ghost"
          disabled={cancel.isPending}
          onClick={() => {
            const reason = window.prompt("Why cancel this request?")
            if (reason?.trim()) void attempt(() => cancel.mutateAsync([r.id, r.version, reason.trim()]), "Request cancelled.")
          }}
        >
          Cancel request
        </Button>
      )}
    </div>
  )
}

export function RequestPage() {
  const { requestId } = useParams()
  const request = useRequest(requestId)
  const reference = useReference()
  const update = useFpodMutation(fpodApi.update)
  const [editing, setEditing] = useState(false)
  const r = request.data

  return (
    <FpodPage title={r ? `${r.reference}: ${r.title}` : "Purchase request"}>
      {request.isPending ? (
        <Loading what="the request" />
      ) : request.isError || !r ? (
        <LoadError what="the request" />
      ) : (
        <div className="space-y-5">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <div className="flex items-center gap-2">
              <Link to="/finance-pod/requests" className="text-sm text-primary hover:underline">
                ← All requests
              </Link>
              <Pill label={REQUEST_STATUS[r.status][0]} tone={REQUEST_STATUS[r.status][1]} />
              <span className="text-sm font-semibold tabular-nums">{money(r.total, r.currency)}</span>
            </div>
            {!editing && <Actions r={r} onEdit={() => setEditing(true)} />}
          </div>

          {r.status === "submitted" && r.current_step && (
            <p className="rounded-lg border border-sky-200 bg-sky-50 px-3 py-2 text-sm text-sky-900">
              Waiting for {r.current_step.capacity}: {r.current_step.approver_name ?? r.current_step.approver_email}{" "}
              (step {r.current_step.step} of {r.route.length}).
            </p>
          )}
          {r.status === "queried" && (
            <p className="rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 text-sm text-amber-900">
              Queried: {r.decisions.at(-1)?.note}. Edit the request and resubmit it.
            </p>
          )}
          {r.status === "approved" && (
            <p className="rounded-lg border border-emerald-200 bg-emerald-50 px-3 py-2 text-sm text-emerald-900">
              Approved: its budget is held. The buyer selects the vendor, then the PO agent drafts the PO.
            </p>
          )}

          {editing ? (
            <Card title="Edit request">
              <RequestForm
                initial={fromRequest(r)}
                reference={reference.data}
                currency={r.currency}
                saving={update.isPending}
                submitLabel="Save changes"
                onCancel={() => setEditing(false)}
                onSubmit={async (body) => {
                  const saved = await attempt(() => update.mutateAsync([r.id, body, r.version]), "Saved. The request agent re-checked it.")
                  if (saved) setEditing(false)
                }}
              />
            </Card>
          ) : (
            <>
            <PoPanel r={r} />
            <SourcingPanel r={r} />
            <div className="grid gap-5 xl:grid-cols-5">
              <div className="space-y-5 xl:col-span-3">
                <Card title="Request">
                  <Facts r={r} reference={reference.data} />
                </Card>
                <Card title="Items and services">
                  <Lines r={r} />
                </Card>
                <Files r={r} />
              </div>
              <div className="space-y-5 xl:col-span-2">
                <DecisionCard r={r} />
                <BudgetCheckCard r={r} />
                <DecisionHistory r={r} />
                <RequestAgent r={r} reference={reference.data} />
              </div>
            </div>
            </>
          )}
        </div>
      )}
    </FpodPage>
  )
}
