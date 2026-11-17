import { useCallback, useEffect, useState, type FormEvent, type ReactNode } from "react"
import {
  CircleCheck,
  Clock,
  Download,
  Eye,
  FileSignature,
  FileText,
  Plus,
  RefreshCw,
  Send,
  Trash2,
  Upload,
  X,
} from "lucide-react"
import { useSearchParams } from "react-router"

import { AppPage } from "@/components/layout/app-page"
import { Alert } from "@/components/ui/alert"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Switch } from "@/components/ui/switch"
import { Textarea } from "@/components/ui/textarea"
import { useCurrentUser } from "@/features/auth/hooks"
import { Card, Empty, LoadError, Loading, Pill } from "@/features/service-pod/components/bits"
import { formatDateTime } from "@/features/service-pod/labels"
import type { Tone } from "@/features/service-pod/labels"
import { errorMessage } from "@/lib/api"
import { cn } from "@/lib/utils"

import {
  esignApi,
  type EsignDocument,
  type EsignTemplate,
  type RecipientInput,
  type SignatureLayout,
  type Stage,
} from "./api"
import {
  useDeleteTemplate,
  useDocument,
  useDocuments,
  useEsignSetup,
  useRefreshDocument,
  useReport,
  useCountersign,
  useRetrySend,
  useSendDocument,
  useTemplates,
  useUploadTemplate,
} from "./hooks"

type Tab = "reports" | "send" | "templates"

const STAGES: { stage: Stage; label: string; tone: Tone }[] = [
  { stage: "preparing", label: "Preparing", tone: "neutral" },
  { stage: "sent", label: "Sent", tone: "info" },
  { stage: "viewed", label: "Viewed", tone: "violet" },
  { stage: "completed", label: "Completed", tone: "good" },
  { stage: "declined", label: "Declined", tone: "bad" },
  { stage: "voided", label: "Voided / expired", tone: "warn" },
  { stage: "failed", label: "Failed", tone: "bad" },
]
const STAGE_TONE = Object.fromEntries(STAGES.map((s) => [s.stage, s.tone])) as Record<Stage, Tone>

const EVENT_LABELS: Record<string, string> = {
  created: "Uploaded to PandaDoc",
  sent: "Emailed to signers",
  send_failed: "Sending failed",
  failed: "Failed",
  refreshed: "Status refreshed",
  document_state_changed: "Status changed",
  recipient_completed: "Signer completed",
  document_creation_failed: "PandaDoc couldn't create it",
  document_completed_pdf_ready: "Signed PDF ready",
  document_updated: "Back to draft",
  document_deleted: "Deleted in PandaDoc",
}

function formatBytes(n: number): string {
  return n >= 1024 * 1024 ? `${(n / (1024 * 1024)).toFixed(1)} MB` : `${Math.max(1, Math.round(n / 1024))} KB`
}

function formatHours(h: number | null): string {
  if (h === null) return "—"
  if (h < 1) return `${Math.max(1, Math.round(h * 60))} min`
  if (h < 48) return `${h.toFixed(1)} h`
  return `${(h / 24).toFixed(1)} days`
}

// --- setup ----------------------------------------------------------------------------------

function SetupNotice() {
  const { data: setup } = useEsignSetup()
  if (!setup) return null
  if (!setup.configured) {
    return (
      <Alert className="mb-5 border-amber-300/60 bg-amber-50 text-amber-900 dark:bg-amber-950/40 dark:text-amber-200">
        E-signature isn't switched on yet. Add <code className="font-mono">PANDADOC_API_KEY</code> to the server's
        environment (PandaDoc → Settings → Dev Center → API keys) and restart. You can upload templates meanwhile.
      </Alert>
    )
  }
  if (!setup.webhook_configured) {
    return (
      <div className="mb-5 rounded-lg border border-sky-200 bg-sky-50 px-4 py-3 text-sm text-sky-900 dark:border-sky-900 dark:bg-sky-950/40 dark:text-sky-200">
        <p className="font-semibold">Live status updates are off</p>
        <p className="mt-1">
          In PandaDoc → Dev Center → Webhooks, add a subscription to{" "}
          <code className="rounded bg-white/70 px-1 font-mono text-xs dark:bg-black/30">{setup.webhook_url}</code> with
          the events <em>document state changed</em> and <em>recipient completed</em>, then put its shared key in{" "}
          <code className="font-mono">PANDADOC_WEBHOOK_KEY</code>. Until then, use “Refresh status” on a document.
        </p>
      </div>
    )
  }
  return null
}

// --- reports --------------------------------------------------------------------------------

function Stat({ label, value, hint, icon }: { label: string; value: ReactNode; hint: string; icon: ReactNode }) {
  return (
    <div className="rounded-xl border border-border/80 bg-card p-4 shadow-2xs">
      <div className="flex items-start justify-between gap-2">
        <span className="text-[11px] font-bold tracking-wider text-muted-foreground uppercase">{label}</span>
        <span className="text-muted-foreground">{icon}</span>
      </div>
      <div className="mt-1 text-2xl font-bold tracking-tight text-brand-navy tabular-nums dark:text-foreground">
        {value}
      </div>
      <p className="mt-1 text-xs text-muted-foreground">{hint}</p>
    </div>
  )
}

function ReportStats() {
  const { data: report, isPending, isError } = useReport()
  if (isPending) return <Loading what="your report" />
  if (isError) return <LoadError what="your report" />
  const banner = report.awaiting_you > 0 && (
    <div className="flex items-center gap-3 rounded-xl border border-amber-300/70 bg-amber-50 px-4 py-3 text-sm text-amber-900 shadow-2xs dark:border-amber-800 dark:bg-amber-950/40 dark:text-amber-200">
      <FileSignature className="size-5 shrink-0" />
      <p>
        <b>
          {report.awaiting_you} document{report.awaiting_you === 1 ? "" : "s"} need
          {report.awaiting_you === 1 ? "s" : ""} your countersignature.
        </b>{" "}
        Everyone else has signed. Open one marked “Your turn” below.
      </p>
    </div>
  )
  const counts = Object.fromEntries(report.by_stage.map((s) => [s.stage, s.count])) as Record<Stage, number>
  return (
    <div className="space-y-4">
      {banner}
      <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
        <Stat
          label="Sent by you"
          value={report.total}
          hint={`${report.sent_last_30_days} in the last 30 days`}
          icon={<Send className="size-4" />}
        />
        <Stat
          label="Awaiting signature"
          value={report.awaiting_signature}
          hint={`${counts.viewed ?? 0} opened, not signed yet`}
          icon={<Clock className="size-4" />}
        />
        <Stat
          label="Completed"
          value={counts.completed ?? 0}
          hint={
            report.completion_rate === null
              ? "Nothing sent yet"
              : `${Math.round(report.completion_rate * 100)}% completion rate`
          }
          icon={<CircleCheck className="size-4" />}
        />
        <Stat
          label="Time to sign"
          value={formatHours(report.avg_hours_to_complete)}
          hint="Average, sent → completed"
          icon={<FileSignature className="size-4" />}
        />
      </div>
      {report.total > 0 && (
        <div className="grid gap-3 lg:grid-cols-2">
          <Card title="By status">
            <div className="flex h-3 overflow-hidden rounded-full bg-muted" aria-hidden>
              {STAGES.filter((s) => counts[s.stage]).map((s) => (
                <div
                  key={s.stage}
                  className={cn("h-full", TONE_BAR[s.tone])}
                  style={{ width: `${(counts[s.stage] / report.total) * 100}%` }}
                  title={`${s.label}: ${counts[s.stage]}`}
                />
              ))}
            </div>
            <ul className="mt-3 grid grid-cols-2 gap-x-4 gap-y-1.5 text-sm sm:grid-cols-3">
              {STAGES.map((s) => (
                <li key={s.stage} className="flex items-center justify-between gap-2">
                  <span className="flex items-center gap-1.5 text-muted-foreground">
                    <span className={cn("size-2 rounded-full", TONE_BAR[s.tone])} aria-hidden />
                    {s.label}
                  </span>
                  <span className="font-semibold tabular-nums">{counts[s.stage] ?? 0}</span>
                </li>
              ))}
            </ul>
          </Card>
          <Card title="By template">
            <table className="w-full text-sm">
              <thead>
                <tr className="text-left text-xs text-muted-foreground">
                  <th className="pb-1.5 font-medium">Template</th>
                  <th className="pb-1.5 text-right font-medium">Sent</th>
                  <th className="pb-1.5 text-right font-medium">Completed</th>
                </tr>
              </thead>
              <tbody>
                {report.templates.slice(0, 6).map((t) => (
                  <tr key={t.template_name} className="border-t border-border/60">
                    <td className="max-w-0 truncate py-1.5 pr-2">{t.template_name}</td>
                    <td className="py-1.5 text-right tabular-nums">{t.sent}</td>
                    <td className="py-1.5 text-right tabular-nums">{t.completed}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </Card>
        </div>
      )}
    </div>
  )
}

const TONE_BAR: Record<Tone, string> = {
  neutral: "bg-slate-400",
  info: "bg-sky-500",
  good: "bg-emerald-500",
  positive: "bg-emerald-500",
  warn: "bg-amber-500",
  bad: "bg-red-500",
  ai: "bg-violet-500",
  violet: "bg-violet-500",
}

function Signers({ doc }: { doc: EsignDocument }) {
  return (
    <div className="space-y-0.5">
      {doc.recipients.map((r) => (
        <div key={r.email} className="flex items-center gap-1.5 text-xs">
          {r.has_completed ? (
            <CircleCheck className="size-3.5 shrink-0 text-emerald-600" aria-label="Signed" />
          ) : (
            <Clock className="size-3.5 shrink-0 text-muted-foreground" aria-label="Not signed yet" />
          )}
          <span className="truncate" title={r.email}>
            {r.countersigner ? "You (countersign)" : r.name || r.email}
          </span>
        </div>
      ))}
    </div>
  )
}

function DocumentsTable({ onOpen }: { onOpen: (id: string) => void }) {
  const [stage, setStage] = useState<Stage | null>(null)
  const [search, setSearch] = useState("")
  const { data, isPending, isError } = useDocuments(stage, search)

  return (
    <Card
      title="Documents you sent"
      hint="Only documents you sent appear here. Other people's documents never do."
      actions={
        <div className="flex flex-wrap items-center gap-2">
          <Input
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="Search name or email"
            className="h-9 w-48"
            aria-label="Search documents"
          />
          <select
            value={stage ?? ""}
            onChange={(e) => setStage((e.target.value || null) as Stage | null)}
            className="h-9 rounded-md border border-input bg-background px-2 text-sm"
            aria-label="Filter by status"
          >
            <option value="">All statuses</option>
            {STAGES.map((s) => (
              <option key={s.stage} value={s.stage}>
                {s.label}
              </option>
            ))}
          </select>
        </div>
      }
    >
      {isPending ? (
        <Loading what="documents" />
      ) : isError ? (
        <LoadError what="documents" />
      ) : data.items.length === 0 ? (
        <Empty icon={<FileSignature className="size-5" />}>
          {stage || search ? "No documents match." : "Nothing sent yet. Send a template for signature to see it here."}
        </Empty>
      ) : (
        <div className="-mx-4 overflow-x-auto">
          <table className="w-full min-w-[720px] text-sm">
            <thead>
              <tr className="border-b border-border text-left text-xs text-muted-foreground">
                <th className="px-4 py-2 font-medium">Document</th>
                <th className="px-2 py-2 font-medium">Signers</th>
                <th className="px-2 py-2 font-medium">Status</th>
                <th className="px-2 py-2 font-medium">Sent</th>
                <th className="px-4 py-2 font-medium">Last update</th>
              </tr>
            </thead>
            <tbody>
              {data.items.map((d) => (
                <tr
                  key={d.id}
                  className="cursor-pointer border-b border-border/60 align-top hover:bg-muted/40"
                  onClick={() => onOpen(d.id)}
                >
                  <td className="px-4 py-2.5">
                    <button
                      type="button"
                      className="text-left font-medium text-brand-navy hover:underline dark:text-foreground"
                      onClick={(e) => {
                        e.stopPropagation()
                        onOpen(d.id)
                      }}
                    >
                      {d.name}
                    </button>
                    <p className="text-xs text-muted-foreground">{d.template_name}</p>
                  </td>
                  <td className="max-w-[220px] px-2 py-2.5">
                    <Signers doc={d} />
                  </td>
                  <td className="px-2 py-2.5">
                    {d.your_turn ? (
                      <Pill label="Your turn" tone="warn" />
                    ) : (
                      <Pill label={d.status_label} tone={d.send_pending ? "neutral" : STAGE_TONE[d.stage]} />
                    )}
                    {d.error && <p className="mt-1 max-w-[200px] text-xs text-red-700">{d.error}</p>}
                  </td>
                  <td className="px-2 py-2.5 text-xs whitespace-nowrap text-muted-foreground">
                    {formatDateTime(d.sent_at ?? d.created_at)}
                  </td>
                  <td className="px-4 py-2.5 text-xs whitespace-nowrap text-muted-foreground">
                    {formatDateTime(d.status_changed_at)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          {data.total > data.items.length && (
            <p className="px-4 pt-2 text-xs text-muted-foreground">
              Showing the latest {data.items.length} of {data.total}.
            </p>
          )}
        </div>
      )}
    </Card>
  )
}

/** PandaDoc's signing screen for my countersignature, inside the app */
function SigningWindow({ url, onSigned, onClose }: { url: string; onSigned: () => void; onClose: () => void }) {
  const [state, setState] = useState<"loading" | "ready" | "signed" | "error">("loading")
  useEffect(() => {
    const onMessage = (event: MessageEvent) => {
      if (!/^https:\/\/app\.pandadoc\.(com|eu)$/.test(event.origin)) return
      const type = (event.data as { type?: string } | null)?.type
      if (type === "session_view.document.loaded") setState("ready")
      if (type === "session_view.document.completed") {
        setState("signed")
        onSigned()
      }
      if (type === "session_view.document.exception") setState("error")
    }
    window.addEventListener("message", onMessage)
    return () => window.removeEventListener("message", onMessage)
  }, [onSigned])

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-2 sm:p-6"
      role="dialog"
      aria-modal
    >
      <div className="flex h-full w-full max-w-5xl flex-col overflow-hidden rounded-xl bg-card shadow-2xl">
        <div className="flex items-center justify-between gap-3 border-b px-4 py-2.5">
          <p className="text-sm font-semibold">
            {state === "signed" ? "Signed. The document is complete once PandaDoc finishes." : "Countersign"}
          </p>
          <div className="flex items-center gap-1">
            <a
              href={url}
              target="_blank"
              rel="noreferrer"
              className="rounded-md px-2 py-1 text-xs text-muted-foreground hover:bg-secondary hover:text-foreground"
            >
              Open in a new tab
            </a>
            <button
              type="button"
              onClick={onClose}
              className="rounded-md p-1.5 text-muted-foreground hover:bg-secondary"
              aria-label="Close"
            >
              <X className="size-4" />
            </button>
          </div>
        </div>
        {state === "error" && (
          <Alert className="m-3">PandaDoc couldn't finish the signature. Close this and try again.</Alert>
        )}
        {state === "signed" ? (
          <div className="flex flex-1 flex-col items-center justify-center gap-3 p-6 text-center">
            <CircleCheck className="size-10 text-emerald-600" />
            <p className="font-semibold">Your countersignature is done.</p>
            <Button onClick={onClose}>Close</Button>
          </div>
        ) : (
          <iframe src={url} title="PandaDoc signing" className="w-full flex-1 border-0" allow="clipboard-write" />
        )}
      </div>
    </div>
  )
}

function DocumentPanel({ id, onClose }: { id: string; onClose: () => void }) {
  const { data: doc, isPending, isError } = useDocument(id)
  const refresh = useRefreshDocument()
  const retry = useRetrySend()
  const countersign = useCountersign()
  const [signingUrl, setSigningUrl] = useState<string | null>(null)
  const [downloadError, setDownloadError] = useState<string | null>(null)
  const error = refresh.error ?? retry.error ?? countersign.error
  const { mutate: refreshNow } = refresh
  // PandaDoc confirms the signature by webhook; read it now too (no webhook locally)
  const onSigned = useCallback(() => {
    setTimeout(() => refreshNow(id), 2500)
  }, [refreshNow, id])

  return (
    <div className="fixed inset-0 z-40 flex justify-end bg-black/30" onClick={onClose}>
      <aside
        className="h-full w-full max-w-md overflow-y-auto bg-card p-5 shadow-xl"
        onClick={(e) => e.stopPropagation()}
        aria-label="Document details"
      >
        <div className="flex items-start justify-between gap-3">
          <h2 className="text-lg font-bold text-brand-navy dark:text-foreground">{doc?.name ?? "Document"}</h2>
          <button
            type="button"
            onClick={onClose}
            className="rounded-md p-1.5 text-muted-foreground hover:bg-secondary"
            aria-label="Close"
          >
            <X className="size-4" />
          </button>
        </div>
        {isPending ? (
          <Loading what="the document" />
        ) : isError ? (
          <LoadError what="the document" />
        ) : (
          <div className="mt-3 space-y-5">
            <div className="flex flex-wrap items-center gap-2">
              <Pill label={doc.status_label} tone={doc.send_pending ? "neutral" : STAGE_TONE[doc.stage]} />
              <span className="text-xs text-muted-foreground">from {doc.template_name}</span>
            </div>
            {doc.your_turn && (
              <div className="rounded-lg border border-amber-300/70 bg-amber-50 p-3 text-sm text-amber-900 dark:border-amber-800 dark:bg-amber-950/40 dark:text-amber-200">
                <p className="font-semibold">Everyone else has signed. Your countersignature is due.</p>
                <Button
                  size="sm"
                  className="mt-2"
                  disabled={countersign.isPending}
                  onClick={() => countersign.mutate(doc.id, { onSuccess: (s) => setSigningUrl(s.url) })}
                >
                  <FileSignature /> {countersign.isPending ? "Opening…" : "Countersign now"}
                </Button>
              </div>
            )}
            {doc.countersign && !doc.your_turn && doc.stage !== "completed" && (
              <p className="text-xs text-muted-foreground">
                You countersign last: this document comes to you once every other signer has signed.
              </p>
            )}
            {doc.error && <Alert>{doc.error}</Alert>}
            {error && <Alert>{errorMessage(error, "PandaDoc didn't answer.")}</Alert>}
            {downloadError && <Alert>{downloadError}</Alert>}
            <div className="flex flex-wrap gap-2">
              {doc.send_pending && (
                <Button size="sm" onClick={() => retry.mutate(doc.id)} disabled={retry.isPending}>
                  <Send /> {retry.isPending ? "Sending…" : "Retry send"}
                </Button>
              )}
              <Button size="sm" variant="outline" onClick={() => refresh.mutate(doc.id)} disabled={refresh.isPending}>
                <RefreshCw className={cn(refresh.isPending && "animate-spin")} /> Refresh status
              </Button>
              {doc.pandadoc_id && (
                <Button
                  size="sm"
                  variant="outline"
                  onClick={() => {
                    setDownloadError(null)
                    esignApi
                      .download(doc)
                      .catch((e: unknown) => setDownloadError(errorMessage(e, "Couldn't download the PDF.")))
                  }}
                >
                  <Download /> {doc.stage === "completed" ? "Signed PDF" : "PDF"}
                </Button>
              )}
            </div>

            <section>
              <h3 className="mb-2 text-xs font-bold tracking-wider text-muted-foreground uppercase">Signers</h3>
              <ul className="space-y-2">
                {doc.recipients.map((r) => (
                  <li key={r.email} className="flex items-center justify-between gap-2 rounded-lg border p-2.5 text-sm">
                    <div className="min-w-0">
                      <p className="truncate font-medium">{r.name || r.email}</p>
                      <p className="truncate text-xs text-muted-foreground">{r.email}</p>
                    </div>
                    {r.countersigner && !r.has_completed ? (
                      <Pill
                        label={doc.your_turn ? "Your turn" : "You, last"}
                        tone={doc.your_turn ? "warn" : "neutral"}
                      />
                    ) : r.has_completed ? (
                      <Pill label={`Signed ${r.completed_at ? formatDateTime(r.completed_at) : ""}`} tone="good" />
                    ) : (
                      <Pill label="Waiting" tone="neutral" />
                    )}
                  </li>
                ))}
              </ul>
            </section>

            <section>
              <h3 className="mb-2 text-xs font-bold tracking-wider text-muted-foreground uppercase">Timeline</h3>
              <dl className="mb-3 grid grid-cols-3 gap-2 text-xs">
                {(
                  [
                    ["Sent", doc.sent_at],
                    ["Viewed", doc.viewed_at],
                    ["Completed", doc.completed_at],
                  ] as const
                ).map(([label, at]) => (
                  <div key={label} className="rounded-md bg-muted/50 p-2">
                    <dt className="text-muted-foreground">{label}</dt>
                    <dd className="mt-0.5 font-medium">{at ? formatDateTime(at) : "—"}</dd>
                  </div>
                ))}
              </dl>
              <ol className="relative space-y-3 border-l border-border pl-4">
                {[...doc.events].reverse().map((e, i) => (
                  <li key={i} className="text-sm">
                    <span className="absolute -left-1 mt-1.5 size-2 rounded-full bg-primary/70" aria-hidden />
                    <p className="font-medium">
                      {EVENT_LABELS[e.event] ?? e.event}
                      {e.recipient_email && <span className="font-normal"> · {e.recipient_email}</span>}
                    </p>
                    <p className="text-xs text-muted-foreground">
                      {formatDateTime(e.created_at)}
                      {e.detail && ` · ${e.detail}`}
                    </p>
                  </li>
                ))}
              </ol>
            </section>
            {Object.keys(doc.field_values).length > 0 && (
              <section className="text-sm">
                <h3 className="mb-2 text-xs font-bold tracking-wider text-muted-foreground uppercase">Filled in</h3>
                <dl className="grid grid-cols-2 gap-x-3 gap-y-1.5">
                  {Object.entries(doc.field_values).map(([k, v]) => (
                    <div key={k}>
                      <dt className="text-xs text-muted-foreground">{humanize(k)}</dt>
                      <dd className="font-medium">{typeof v === "boolean" ? (v ? "Yes" : "No") : v}</dd>
                    </div>
                  ))}
                </dl>
              </section>
            )}
            {doc.subject && (
              <section className="text-sm">
                <h3 className="mb-1 text-xs font-bold tracking-wider text-muted-foreground uppercase">Email</h3>
                <p className="font-medium">{doc.subject}</p>
                {doc.message && <p className="mt-1 whitespace-pre-line text-muted-foreground">{doc.message}</p>}
              </section>
            )}
          </div>
        )}
      </aside>
      {signingUrl && doc && (
        <div onClick={(e) => e.stopPropagation()}>
          <SigningWindow
            url={signingUrl}
            onSigned={onSigned}
            onClose={() => {
              setSigningUrl(null)
              refresh.mutate(doc.id)
            }}
          />
        </div>
      )}
    </div>
  )
}

// --- send -----------------------------------------------------------------------------------

const BLANK: RecipientInput = { email: "", first_name: "", last_name: "" }

function SendForm({ onSent, initialTemplate }: { onSent: (id: string) => void; initialTemplate: string | null }) {
  const { data: templates, isPending } = useTemplates()
  const { data: setup } = useEsignSetup()
  const send = useSendDocument()
  const [templateId, setTemplateId] = useState(initialTemplate ?? "")
  const [name, setName] = useState("")
  const [recipients, setRecipients] = useState<RecipientInput[]>([{ ...BLANK }])
  const [subject, setSubject] = useState("")
  const [message, setMessage] = useState("")
  // The dynamic fields' values, per template
  const [values, setValues] = useState<Record<string, Record<string, string>>>({})
  const [countersign, setCountersign] = useState(false)
  const { data: me } = useCurrentUser()

  if (isPending) return <Loading what="templates" />
  if (!templates?.length) {
    return (
      <Empty icon={<FileText className="size-5" />}>Upload a template first (Templates tab), then send it here.</Empty>
    )
  }
  const chosen = templateId || templates[0].id
  const template = templates.find((t) => t.id === chosen) ?? templates[0]
  // Countersigning, I am the template's last signer: the others fill the rows before me
  const needed = Math.max(1, template.signers_needed - (countersign ? 1 : 0))
  // As many signer rows as the template's tags expect (signer2 -> at least two)
  const rows =
    recipients.length >= needed
      ? recipients
      : [...recipients, ...Array.from({ length: needed - recipients.length }, () => ({ ...BLANK }))]
  const update = (i: number, patch: Partial<RecipientInput>) =>
    setRecipients(rows.map((r, j) => (j === i ? { ...r, ...patch } : r)))
  const fillable = template.field_tags.filter((t) => t.prefillable)
  const signerFields = template.field_tags.filter((t) => !t.prefillable)
  const own = values[chosen] ?? {}
  const setValue = (id: string, v: string) => setValues((all) => ({ ...all, [chosen]: { ...own, [id]: v } }))

  const submit = (e: FormEvent) => {
    e.preventDefault()
    send.mutate(
      {
        template_id: chosen,
        name: name.trim() || undefined,
        recipients: rows.map((r) => ({ ...r, email: r.email.trim() })),
        subject: subject.trim() || undefined,
        message: message.trim() || undefined,
        values: Object.fromEntries(Object.entries(own).filter(([, v]) => v.trim())),
        countersign,
      },
      {
        onSuccess: (doc) => {
          setRecipients([{ ...BLANK }])
          setValues((all) => ({ ...all, [chosen]: {} }))
          setCountersign(false)
          setName("")
          onSent(doc.id)
        },
      },
    )
  }

  return (
    <form onSubmit={submit} className="grid gap-5 lg:grid-cols-[minmax(0,1fr)_320px]">
      <Card title="Send for signature" hint="PandaDoc emails each signer a secure link to sign.">
        <div className="space-y-4">
          <div className="grid gap-3 sm:grid-cols-2">
            <div className="space-y-1.5">
              <Label htmlFor="es-template">Template</Label>
              <select
                id="es-template"
                value={chosen}
                onChange={(e) => setTemplateId(e.target.value)}
                className="h-10 w-full rounded-md border border-input bg-background px-3 text-sm"
              >
                {templates.map((t) => (
                  <option key={t.id} value={t.id}>
                    {t.name}
                  </option>
                ))}
              </select>
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="es-name">Document name (optional)</Label>
              <Input
                id="es-name"
                value={name}
                onChange={(e) => setName(e.target.value)}
                placeholder={templates.find((t) => t.id === chosen)?.name}
                maxLength={255}
              />
            </div>
          </div>

          <fieldset className="space-y-2">
            <legend className="text-sm font-medium">Signers</legend>
            {rows.map((r, i) => (
              <div
                key={i}
                className="grid items-end gap-2 rounded-lg border border-border/80 p-3 sm:grid-cols-[1.4fr_1fr_1fr_auto]"
              >
                <div className="space-y-1">
                  <Label htmlFor={`es-email-${i}`} className="text-xs">
                    Email · signer{i + 1}
                  </Label>
                  <Input
                    id={`es-email-${i}`}
                    type="email"
                    required
                    value={r.email}
                    onChange={(e) => update(i, { email: e.target.value })}
                    placeholder="name@company.com"
                  />
                </div>
                <div className="space-y-1">
                  <Label htmlFor={`es-first-${i}`} className="text-xs">
                    First name
                  </Label>
                  <Input
                    id={`es-first-${i}`}
                    required
                    value={r.first_name}
                    onChange={(e) => update(i, { first_name: e.target.value })}
                  />
                </div>
                <div className="space-y-1">
                  <Label htmlFor={`es-last-${i}`} className="text-xs">
                    Last name
                  </Label>
                  <Input
                    id={`es-last-${i}`}
                    value={r.last_name}
                    onChange={(e) => update(i, { last_name: e.target.value })}
                  />
                </div>
                <Button
                  type="button"
                  variant="ghost"
                  size="icon"
                  disabled={rows.length <= needed}
                  onClick={() => setRecipients(rows.filter((_, j) => j !== i))}
                  aria-label={`Remove signer ${i + 1}`}
                >
                  <Trash2 />
                </Button>
              </div>
            ))}
            {countersign && (
              <div className="flex items-center gap-3 rounded-lg border border-dashed border-primary/40 bg-primary/5 p-3 text-sm">
                <FileSignature className="size-4 shrink-0 text-primary" />
                <div className="min-w-0">
                  <p className="font-medium">
                    signer{rows.length + 1} · You{me ? ` (${me.email})` : ""}
                  </p>
                  <p className="text-xs text-muted-foreground">
                    You get the document after everyone above has signed, and sign it here in one click.
                  </p>
                </div>
              </div>
            )}
            {rows.length + (countersign ? 1 : 0) < 10 && (
              <Button type="button" variant="outline" size="sm" onClick={() => setRecipients([...rows, { ...BLANK }])}>
                <Plus /> Add signer
              </Button>
            )}
            <label className="flex items-start gap-3 rounded-lg border border-border/80 p-3">
              <Switch
                checked={countersign}
                onCheckedChange={setCountersign}
                aria-label="I countersign after the signers"
              />
              <span className="text-sm">
                <span className="font-medium">I countersign after the signers</span>
                <span className="block text-xs text-muted-foreground">
                  The signers above sign first. Then the document comes to you: it shows as “Your turn”, and you sign it
                  inside the app.
                </span>
              </span>
            </label>
          </fieldset>

          {fillable.length > 0 && (
            <fieldset className="space-y-3 rounded-lg border border-violet-200/80 bg-violet-50/40 p-3 dark:border-violet-900 dark:bg-violet-950/20">
              <legend className="px-1 text-sm font-medium">Fill in the template</legend>
              <p className="text-xs text-muted-foreground">
                These values go into the document before it's sent. Leave one empty and the signer fills it in.
              </p>
              <div className="grid gap-3 sm:grid-cols-2">
                {fillable.map((t) => {
                  const id = t.id!
                  const label = `${humanize(id)}${t.required ? "" : " (optional)"}`
                  if (t.type === "checkbox") {
                    return (
                      <label key={id} className="flex items-center gap-2 pt-6 text-sm">
                        <input
                          type="checkbox"
                          checked={own[id] === "true"}
                          onChange={(e) => setValue(id, e.target.checked ? "true" : "")}
                        />
                        {label}
                      </label>
                    )
                  }
                  return (
                    <div key={id} className="space-y-1">
                      <Label htmlFor={`es-v-${id}`} className="text-xs">
                        {label} <span className="font-normal text-muted-foreground">· {t.role}</span>
                      </Label>
                      <Input
                        id={`es-v-${id}`}
                        type={t.type === "date" ? "date" : "text"}
                        value={own[id] ?? ""}
                        onChange={(e) => setValue(id, e.target.value)}
                        maxLength={1000}
                      />
                    </div>
                  )
                })}
              </div>
            </fieldset>
          )}
          {signerFields.length > 0 && (
            <p className="text-xs text-muted-foreground">
              Signers fill in: {signerFields.map((t) => `${FIELD_LABELS[t.type] ?? t.type} (${t.role})`).join(", ")}
            </p>
          )}
          <div className="space-y-1.5">
            <Label htmlFor="es-subject">Email subject (optional)</Label>
            <Input id="es-subject" value={subject} onChange={(e) => setSubject(e.target.value)} maxLength={255} />
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="es-message">Message (optional)</Label>
            <Textarea
              id="es-message"
              rows={3}
              value={message}
              onChange={(e) => setMessage(e.target.value)}
              maxLength={4000}
            />
          </div>
          {send.error && <Alert>{errorMessage(send.error, "PandaDoc didn't take the document.")}</Alert>}
          <Button type="submit" disabled={send.isPending || setup?.configured === false}>
            <Send /> {send.isPending ? "Uploading to PandaDoc…" : "Send for signature"}
          </Button>
        </div>
      </Card>
      <Card title="Where do signers sign?">
        <div className="space-y-2 text-sm text-muted-foreground">
          <p>
            Each template says where signers sign (Templates tab): a signature box at a fixed position, added for every
            signer (the next one below the previous), or PandaDoc field tags in the file.
          </p>
          <p>
            With field tags, the first signer is{" "}
            <code className="rounded bg-muted px-1 font-mono text-xs text-foreground">signer1</code>, the second{" "}
            <code className="rounded bg-muted px-1 font-mono text-xs text-foreground">signer2</code>, and so on:
          </p>
          <pre className="rounded-md bg-muted p-2 font-mono text-xs text-foreground">
            {"{signature:signer1___}\n{date:signer1}\n{initials:signer2}"}
          </pre>
          <p>Underscores widen the field. Use white text if the tag shouldn't show.</p>
        </div>
      </Card>
    </form>
  )
}

// --- templates ------------------------------------------------------------------------------

const FIELD_LABELS: Record<string, string> = {
  textfield: "Text",
  date: "Date",
  checkbox: "Checkbox",
  signature: "Signature",
  initials: "Initials",
  dropdown: "Dropdown",
  radio: "Choice",
  stamp: "Stamp",
}

function humanize(id: string): string {
  const words = id
    .replace(/[-]+/g, " ")
    .replace(/([a-z])([A-Z])/g, "$1 $2")
    .trim()
  return words.charAt(0).toUpperCase() + words.slice(1)
}

function FieldChips({ template }: { template: EsignTemplate }) {
  if (!template.field_tags.length) return null
  return (
    <div className="mt-1.5 flex flex-wrap gap-1">
      {template.field_tags.map((t, i) => (
        <span
          key={i}
          className={cn(
            "rounded px-1.5 py-0.5 text-[10px] font-medium",
            t.prefillable
              ? "bg-violet-50 text-violet-800 dark:bg-violet-950/50 dark:text-violet-300"
              : "bg-muted text-muted-foreground",
          )}
          title={t.prefillable ? "You fill this in when sending" : `${t.role} fills this in`}
        >
          {t.id ? humanize(t.id) : (FIELD_LABELS[t.type] ?? t.type)} · {t.role}
        </span>
      ))}
    </div>
  )
}

const TAG_EXAMPLES: [string, string][] = [
  ["{signature:signer1___}", "Signer 1 signs here"],
  ["{date:signer1}", "Signer 1's signing date"],
  ["{initials:signer2}", "Signer 2's initials"],
  ["{textfield:signer1:company_________}", "Text you fill in when sending (id: company)"],
  ["{date:signer1:start-date___}", "A date you fill in when sending"],
  ["{checkbox:signer1:agree}", "A checkbox (tick it when sending, or let the signer)"],
  ["{t*:signer1:po-number___}", "* = optional; t is short for textfield"],
]

function FieldGuide() {
  return (
    <Card
      title="Dynamic fields: how to mark them"
      hint="Type a field tag into your Word or PDF template exactly where the field should appear."
    >
      <div className="space-y-3 text-sm">
        <p className="rounded-md bg-muted px-2.5 py-1.5 font-mono text-xs">
          {"{"}type<span className="text-muted-foreground">*</span>:signerN
          <span className="text-muted-foreground">:id</span>
          ___{"}"}
        </p>
        <ul className="space-y-1 text-xs text-muted-foreground">
          <li>
            <b className="text-foreground">type</b>: textfield (t), date (d), checkbox (c), signature (s), initials (i)
          </li>
          <li>
            <b className="text-foreground">signerN</b>: who it belongs to: signer1 is the first signer you add, signer2
            the second…
          </li>
          <li>
            <b className="text-foreground">id</b> (optional): name it, and you can fill it in on the Send tab. Letters,
            digits and dashes only, no spaces or underscores.
          </li>
          <li>
            <b className="text-foreground">___</b>: each underscore makes the field wider. <b>*</b> after the type makes
            it optional.
          </li>
        </ul>
        <dl className="divide-y divide-border/60 text-xs">
          {TAG_EXAMPLES.map(([tag, what]) => (
            <div key={tag} className="py-1.5">
              <dt className="font-mono break-all text-foreground">{tag}</dt>
              <dd className="text-muted-foreground">{what}</dd>
            </div>
          ))}
        </dl>
        <p className="text-xs text-muted-foreground">
          Tips: write each tag on one line in one font (Word: type it in one go, don't paste in pieces). Make the tag
          text white or very small if you don't want it seen behind the field. A PDF must have real text, not a scan.
          After uploading, the template shows the fields found; if one is missing, retype that tag.
        </p>
      </div>
    </Card>
  )
}

const LAYOUT_FIELDS: { key: keyof SignatureLayout; label: string; min: number }[] = [
  { key: "page", label: "Page", min: 1 },
  { key: "x", label: "X", min: 0 },
  { key: "y", label: "Y", min: 0 },
  { key: "width", label: "Width", min: 1 },
  { key: "height", label: "Height", min: 1 },
]

function UploadTemplate() {
  const upload = useUploadTemplate()
  const { data: setup } = useEsignSetup()
  const [file, setFile] = useState<File | null>(null)
  const [name, setName] = useState("")
  const [description, setDescription] = useState("")
  const [key, setKey] = useState(0)
  const [useTags, setUseTags] = useState(false)
  // null until edited: the server's default position (PANDADOC_SIGNATURE_*)
  const [edited, setEdited] = useState<Partial<Record<keyof SignatureLayout, string>>>({})
  const defaults = setup?.default_layout
  const value = (k: keyof SignatureLayout) => edited[k] ?? (defaults ? String(defaults[k]) : "")

  const submit = (e: FormEvent) => {
    e.preventDefault()
    if (!file) return
    const layout = useTags
      ? null
      : (Object.fromEntries(LAYOUT_FIELDS.map(({ key: k }) => [k, Number(value(k))])) as unknown as SignatureLayout)
    upload.mutate(
      { file, name: name.trim() || file.name.replace(/\.[^.]+$/, ""), description, layout },
      {
        onSuccess: () => {
          setFile(null)
          setName("")
          setDescription("")
          setKey((k) => k + 1)
        },
      },
    )
  }

  return (
    <Card
      title="Upload a template"
      hint={`PDF, Word (.docx) or RTF, up to ${setup ? Math.round(setup.max_bytes / (1024 * 1024)) : 10} MB. Only you can see your templates.`}
    >
      <form onSubmit={submit} className="space-y-3">
        <div className="space-y-1.5">
          <Label htmlFor="es-file">File</Label>
          <Input
            key={key}
            id="es-file"
            type="file"
            required
            accept=".pdf,.docx,.rtf,application/pdf,application/vnd.openxmlformats-officedocument.wordprocessingml.document,application/rtf"
            onChange={(e) => {
              const f = e.target.files?.[0] ?? null
              setFile(f)
              if (f && !name) setName(f.name.replace(/\.[^.]+$/, ""))
            }}
          />
        </div>
        <div className="space-y-1.5">
          <Label htmlFor="es-tname">Name</Label>
          <Input
            id="es-tname"
            value={name}
            onChange={(e) => setName(e.target.value)}
            maxLength={200}
            placeholder="e.g. Engagement letter"
          />
        </div>
        <div className="space-y-1.5">
          <Label htmlFor="es-tdesc">Description (optional)</Label>
          <Input id="es-tdesc" value={description} onChange={(e) => setDescription(e.target.value)} maxLength={2000} />
        </div>
        <fieldset className="space-y-2 rounded-lg border border-border/80 p-3">
          <legend className="px-1 text-sm font-medium">Where signers sign</legend>
          <label className="flex items-start gap-2 text-sm">
            <input
              type="radio"
              name="es-placement"
              checked={!useTags}
              onChange={() => setUseTags(false)}
              className="mt-1"
            />
            <span>
              Signature box at a fixed position
              <span className="block text-xs text-muted-foreground">
                Points from the page's top-left corner (A4/Letter is about 600 × 800). More signers: each box goes below
                the previous one.
              </span>
            </span>
          </label>
          {!useTags && (
            <div className="grid grid-cols-3 gap-2 pl-6">
              {LAYOUT_FIELDS.map(({ key: k, label, min }) => (
                <div key={k} className="space-y-1">
                  <Label htmlFor={`es-l-${k}`} className="text-[11px]">
                    {label}
                  </Label>
                  <Input
                    id={`es-l-${k}`}
                    type="number"
                    required
                    min={min}
                    step={k === "page" ? 1 : "any"}
                    value={value(k)}
                    onChange={(e) => setEdited((x) => ({ ...x, [k]: e.target.value }))}
                    className="h-9 px-2"
                  />
                </div>
              ))}
            </div>
          )}
          <label className="flex items-start gap-2 text-sm">
            <input
              type="radio"
              name="es-placement"
              checked={useTags}
              onChange={() => setUseTags(true)}
              className="mt-1"
            />
            <span>
              Field tags in the file
              <span className="block text-xs text-muted-foreground">
                e.g. <code className="font-mono">{"{signature:signer1___}"}</code> where each signer signs. A file with
                signature tags always uses them.
              </span>
            </span>
          </label>
        </fieldset>
        {upload.error && <Alert>{errorMessage(upload.error, "Couldn't upload the template.")}</Alert>}
        <Button type="submit" disabled={!file || upload.isPending}>
          <Upload /> {upload.isPending ? "Uploading…" : "Upload template"}
        </Button>
      </form>
    </Card>
  )
}

function TemplateList({ onSend }: { onSend: (t: EsignTemplate) => void }) {
  const { data: templates, isPending, isError } = useTemplates()
  const remove = useDeleteTemplate()
  if (isPending) return <Loading what="templates" />
  if (isError) return <LoadError what="templates" />
  return (
    <Card title="Your templates" hint="Removing a template keeps the documents already sent from it.">
      {templates.length === 0 ? (
        <Empty icon={<FileText className="size-5" />}>No templates yet.</Empty>
      ) : (
        <ul className="divide-y divide-border/70">
          {templates.map((t) => (
            <li key={t.id} className="flex items-start justify-between gap-3 py-3">
              <div className="flex min-w-0 flex-1 items-start gap-3">
                <span className="flex size-9 shrink-0 items-center justify-center rounded-lg bg-sky-50 text-sky-700 dark:bg-sky-950/50 dark:text-sky-300">
                  <FileText className="size-4" />
                </span>
                <div className="min-w-0">
                  <p className="truncate font-medium">{t.name}</p>
                  <p className="truncate text-xs text-muted-foreground">
                    {t.filename} · {formatBytes(t.size_bytes)} · sent {t.times_sent}× ·{" "}
                    {t.signature_layout
                      ? `signature on page ${t.signature_layout.page} at ${t.signature_layout.x}, ${t.signature_layout.y}`
                      : "field tags"}
                    {t.description && ` · ${t.description}`}
                  </p>
                  <FieldChips template={t} />
                </div>
              </div>
              <div className="flex shrink-0 gap-1.5">
                <Button size="sm" onClick={() => onSend(t)}>
                  <Send /> Send
                </Button>
                <Button
                  size="sm"
                  variant="ghost"
                  onClick={() => void esignApi.downloadTemplate(t)}
                  aria-label={`Download ${t.name}`}
                >
                  <Eye />
                </Button>
                <Button
                  size="sm"
                  variant="ghost"
                  disabled={remove.isPending}
                  onClick={() => {
                    if (window.confirm(`Remove the template “${t.name}”?`)) remove.mutate(t.id)
                  }}
                  aria-label={`Remove ${t.name}`}
                >
                  <Trash2 />
                </Button>
              </div>
            </li>
          ))}
        </ul>
      )}
    </Card>
  )
}

// --- page -----------------------------------------------------------------------------------

const TABS: { key: Tab; label: string }[] = [
  { key: "reports", label: "Reports" },
  { key: "send", label: "Send" },
  { key: "templates", label: "Templates" },
]

export function EsignPage() {
  const [params, setParams] = useSearchParams()
  const tab = (TABS.some((t) => t.key === params.get("tab")) ? params.get("tab") : "reports") as Tab
  const [openId, setOpenId] = useState<string | null>(null)
  const [sendTemplate, setSendTemplate] = useState<string | null>(null)
  const go = (next: Tab) => setParams(next === "reports" ? {} : { tab: next }, { replace: true })

  return (
    <AppPage
      title="E-Signature"
      subtitle="Upload your templates, send them for signature through PandaDoc, and follow every document you sent."
    >
      <SetupNotice />
      <div
        role="tablist"
        aria-label="E-signature"
        className="mb-5 inline-flex rounded-lg border border-border bg-card p-1 shadow-2xs"
      >
        {TABS.map((t) => (
          <button
            key={t.key}
            type="button"
            role="tab"
            aria-selected={tab === t.key}
            onClick={() => go(t.key)}
            className={cn(
              "rounded-md px-4 py-1.5 text-sm font-medium transition-colors",
              tab === t.key ? "bg-brand-navy text-white" : "text-muted-foreground hover:text-foreground",
            )}
          >
            {t.label}
          </button>
        ))}
      </div>

      {tab === "reports" && (
        <div className="space-y-5">
          <ReportStats />
          <DocumentsTable onOpen={setOpenId} />
        </div>
      )}
      {tab === "send" && (
        <SendForm
          key={sendTemplate ?? "send"}
          initialTemplate={sendTemplate}
          onSent={(id) => {
            go("reports")
            setOpenId(id)
          }}
        />
      )}
      {tab === "templates" && (
        <div className="grid gap-5 lg:grid-cols-[minmax(0,1fr)_360px]">
          <TemplateList
            onSend={(t) => {
              setSendTemplate(t.id)
              go("send")
            }}
          />
          <div className="space-y-5">
            <UploadTemplate />
            <FieldGuide />
          </div>
        </div>
      )}
      {openId && <DocumentPanel id={openId} onClose={() => setOpenId(null)} />}
    </AppPage>
  )
}
