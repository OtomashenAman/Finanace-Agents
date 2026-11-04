import { useState } from "react"
import { Link, useSearchParams } from "react-router"
import { Bot, ExternalLink, Headset, UserRound } from "lucide-react"

import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Textarea } from "@/components/ui/textarea"
import { AiBadge, AiCard, Card, Empty, LoadError, Loading, Pill } from "@/features/service-pod/components/bits"
import { formatDateTime } from "@/features/service-pod/labels"
import { attempt } from "@/features/service-pod/ui"
import { cn } from "@/lib/utils"

import { FpodPage } from "./components/fpod-page"
import { useFpodMutation, useVendorQueries } from "./hooks"
import { QUERY_INTENT, QUERY_STATUS } from "./labels"
import { paymentsApi, type VendorQuery } from "./payments-api"

const FILTERS: (string | null)[] = [null, "escalated", "answered", "resolved"]

function Reply({ q }: { q: VendorQuery }) {
  const reply = useFpodMutation(paymentsApi.reply)
  const [text, setText] = useState("")
  return (
    <div className="mt-2 space-y-2">
      <Textarea rows={3} value={text} onChange={(e) => setText(e.target.value)} placeholder="Your answer to the vendor (emailed to the address on file)" />
      <Button size="sm" disabled={reply.isPending || text.trim().length < 3} onClick={() => attempt(() => reply.mutateAsync([q.id, text]), "Answer sent.")}>
        Send answer
      </Button>
    </div>
  )
}

function LogQuery() {
  const log = useFpodMutation(paymentsApi.logQuery)
  const [open, setOpen] = useState(false)
  const [email, setEmail] = useState("")
  const [number, setNumber] = useState("")
  const [question, setQuestion] = useState("")
  if (!open)
    return (
      <Button size="sm" variant="outline" onClick={() => setOpen(true)}>
        Log a query from phone or email
      </Button>
    )
  return (
    <div className="space-y-2 rounded-lg border border-border p-3">
      <div className="grid gap-2 sm:grid-cols-2">
        <Input type="email" placeholder="Vendor's email" value={email} onChange={(e) => setEmail(e.target.value)} />
        <Input placeholder="Invoice number (if any)" value={number} onChange={(e) => setNumber(e.target.value)} />
      </div>
      <Textarea rows={2} placeholder="Their question" value={question} onChange={(e) => setQuestion(e.target.value)} />
      <div className="flex gap-2">
        <Button
          size="sm"
          disabled={log.isPending || !email || question.trim().length < 5}
          onClick={async () => {
            const r = await attempt(() => log.mutateAsync([email, number || null, question]), (x) =>
              x.status === "answered" ? `${x.reference}: the vendor agent answered it.` : `${x.reference}: with an analyst.`,
            )
            if (r) setOpen(false)
          }}
        >
          Ask the vendor agent
        </Button>
        <Button size="sm" variant="ghost" onClick={() => setOpen(false)}>
          Cancel
        </Button>
      </div>
    </div>
  )
}

export function VendorQueriesPage() {
  const [params, setParams] = useSearchParams()
  const status = params.get("status") || null
  const list = useVendorQueries(status)
  return (
    <FpodPage title="Vendor queries" subtitle="The vendor agent answers status questions from the records within minutes; disputes and escalations come to an analyst.">
      <div className="space-y-5">
        <AiCard
          title="Vendors ask here"
          hint="A self-service help page vendors can use without logging in. Answers go only to the email address we hold for the vendor."
          badge={<AiBadge label="Vendor agent" />}
          actions={
            <a href="/vendor-help" target="_blank" rel="noreferrer" className="flex items-center gap-1 text-xs font-medium text-primary hover:underline">
              Open the vendor help page <ExternalLink className="size-3.5" aria-hidden />
            </a>
          }
        >
          <LogQuery />
        </AiCard>
        <Card
          title="Queries"
          actions={
            <div className="flex flex-wrap gap-1">
              {FILTERS.map((f) => (
                <button
                  key={f ?? "all"}
                  type="button"
                  onClick={() => setParams(f ? { status: f } : {}, { replace: true })}
                  className={cn("rounded-full border px-2.5 py-0.5 text-xs", status === f ? "border-primary bg-primary text-primary-foreground" : "border-border hover:bg-muted")}
                >
                  {f ? QUERY_STATUS[f][0] : "All"}
                </button>
              ))}
            </div>
          }
        >
          {list.isPending ? (
            <Loading what="queries" />
          ) : list.isError ? (
            <LoadError what="queries" />
          ) : list.data.length === 0 ? (
            <Empty icon={<Headset className="size-5" />}>No vendor queries{status ? " with this status" : " yet"}.</Empty>
          ) : (
            <ul className="divide-y divide-border/60">
              {list.data.map((q) => (
                <li key={q.id} className="py-3 text-sm">
                  <div className="flex flex-wrap items-start justify-between gap-2">
                    <div className="min-w-0">
                      <p>
                        <strong>{q.reference}</strong> · {q.vendor_name ?? q.from_email}
                        {q.invoice_number && (
                          <>
                            {" · "}
                            {q.invoice_id ? (
                              <Link to={`/finance-pod/invoices/${q.invoice_id}`} className="text-primary hover:underline">
                                {q.invoice_number}
                              </Link>
                            ) : (
                              q.invoice_number
                            )}
                          </>
                        )}
                        <span className="text-xs text-muted-foreground"> · {q.via === "portal" ? "help page" : "logged in the app"} · {formatDateTime(q.created_at)}</span>
                      </p>
                      <p className="mt-1 italic text-muted-foreground">“{q.question}”</p>
                    </div>
                    <span className="flex items-center gap-1.5">
                      <Pill label={QUERY_INTENT[q.intent] ?? q.intent} tone="neutral" />
                      <Pill label={QUERY_STATUS[q.status][0]} tone={QUERY_STATUS[q.status][1]} />
                    </span>
                  </div>
                  {q.answer && (
                    <p className="mt-2 flex items-start gap-1.5 rounded-lg bg-muted/40 px-3 py-2">
                      {q.answered_by_name === "Vendor agent" ? (
                        <Bot className="mt-0.5 size-4 shrink-0 text-violet-600" aria-hidden />
                      ) : (
                        <UserRound className="mt-0.5 size-4 shrink-0 text-sky-700" aria-hidden />
                      )}
                      <span>
                        {q.answer}
                        <span className="block text-xs text-muted-foreground">
                          {q.answered_by_name} · {q.response_minutes !== null && `${q.response_minutes} min after the question`}
                        </span>
                      </span>
                    </p>
                  )}
                  {q.status === "escalated" && (
                    <>
                      <p className="mt-1 text-xs text-amber-800">{q.escalation_reason}</p>
                      <Reply q={q} />
                    </>
                  )}
                </li>
              ))}
            </ul>
          )}
        </Card>
      </div>
    </FpodPage>
  )
}
