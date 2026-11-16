import { useState } from "react"
import { BookmarkPlus, Bot, SendHorizontal, Trash2, User } from "lucide-react"

import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"

import type { CaseDetail } from "../api"
import { useAssist, useDeleteTemplate, useEmailTemplate, useSaveTemplate } from "../hooks"
import { formatDateTime } from "../labels"
import { AiBadge } from "./bits"
import { attempt } from "../ui"

const QUICK = [
  ["Friendlier", "Make it warmer and friendlier, same content."],
  ["Firmer", "Make it firmer and more direct about paying, still polite."],
  ["Shorter", "Make it shorter: keep only what's needed."],
  ["More formal", "Make it more formal."],
] as const

interface Turn {
  from: "you" | "ai"
  text: string
  failed?: boolean
}

interface EmailAssistProps {
  c: CaseDetail
  purpose: string
  subject: string
  body: string
  /** The invoices the email is about (null: all of the case's) */
  invoiceNumbers?: string[] | null
  onChange: (subject: string, body: string) => void
}

/** Chat with the AI about the email: ask in plain English to write or change it (the invoice
 *  table stays as the source gives it), and keep this customer's format as their template. */
export function EmailAssist({ c, purpose, subject, body, invoiceNumbers = null, onChange }: EmailAssistProps) {
  const assist = useAssist()
  const [ask, setAsk] = useState("")
  const [turns, setTurns] = useState<Turn[]>([])
  const customer = (c.state as { customer?: { id?: string; name?: string } }).customer
  const empty = !body.trim()
  const run = (instruction: string) => {
    setTurns((t) => [...t, { from: "you", text: instruction }])
    setAsk("")
    void attempt(
      () => assist.mutateAsync({ caseId: c.id, purpose, instruction, subject, body, invoice_numbers: invoiceNumbers }),
      "AI draft ready: check it before saving. The invoice table is unchanged.",
    ).then((r) => {
      if (!r) {
        setTurns((t) => [...t, { from: "ai", text: "I couldn't do that one (see the message on screen). Try rephrasing.", failed: true }])
        return
      }
      onChange(r.subject, r.body)
      setTurns((t) => [...t, { from: "ai", text: `Done: the email is updated${r.subject !== subject ? ` (subject: "${r.subject}")` : ""}. The invoice table is unchanged.` }])
    })
  }

  return (
    <div className="overflow-hidden rounded-xl border border-ai-border bg-ai-soft/40">
      <div className="flex flex-wrap items-center gap-1.5 border-b border-ai-border/60 px-3 py-2 text-xs text-ai-foreground">
        <AiBadge label="AI assist" />
        <span>{empty ? "Tell the AI what email you want." : "Ask the AI to change this email."} Figures always come from the source.</span>
      </div>

      <div className="max-h-56 space-y-2 overflow-y-auto px-3 py-2" aria-live="polite">
        {turns.length === 0 && (
          <Bubble from="ai">
            {empty
              ? "Hi! Describe the email, e.g. \"a polite first reminder asking when they'll pay\", or use Write draft above."
              : "Want it friendlier, firmer or shorter? Pick one below or type your own request."}
          </Bubble>
        )}
        {turns.map((t, i) => (
          <Bubble key={i} from={t.from} failed={t.failed}>
            {t.text}
          </Bubble>
        ))}
        {assist.isPending && <Bubble from="ai">Writing…</Bubble>}
      </div>

      <div className="space-y-2 border-t border-ai-border/60 bg-background/60 px-3 py-2">
        {!empty && (
          <div className="flex flex-wrap gap-1.5">
            {QUICK.map(([label, instruction]) => (
              <button
                key={label}
                type="button"
                disabled={assist.isPending}
                onClick={() => run(instruction)}
                className="rounded-full border border-ai-border bg-background px-2.5 py-0.5 text-xs text-ai-foreground hover:bg-ai-soft disabled:opacity-50"
              >
                {label}
              </button>
            ))}
          </div>
        )}
        <div className="flex gap-2">
          <Input
            value={ask}
            onChange={(e) => setAsk(e.target.value)}
            placeholder={empty ? "e.g. a polite first reminder asking when they'll pay" : "e.g. mention we can share timesheets, ask for a call this week"}
            onKeyDown={(e) => {
              if (e.key === "Enter" && ask.trim().length > 1 && !assist.isPending) {
                e.preventDefault()
                run(ask.trim())
              }
            }}
            aria-label="Ask the AI"
          />
          <Button type="button" size="sm" disabled={assist.isPending || ask.trim().length < 2} onClick={() => run(ask.trim())} aria-label="Send to the AI">
            <SendHorizontal />
          </Button>
        </div>
        {customer?.id && (
          <TemplateBar c={c} purpose={purpose} subject={subject} body={body} invoiceNumbers={invoiceNumbers} name={customer.name ?? "this customer"} />
        )}
      </div>
    </div>
  )
}

function Bubble({ from, failed, children }: { from: Turn["from"]; failed?: boolean; children: string }) {
  const you = from === "you"
  return (
    <div className={`flex items-end gap-1.5 ${you ? "flex-row-reverse" : ""}`}>
      <span className={`grid size-6 shrink-0 place-items-center rounded-full ${you ? "bg-primary text-primary-foreground" : "bg-ai-soft text-ai-foreground"}`} aria-hidden>
        {you ? <User className="size-3.5" /> : <Bot className="size-3.5" />}
      </span>
      <p
        className={`max-w-[85%] rounded-2xl px-3 py-1.5 text-xs whitespace-pre-wrap ${
          you ? "rounded-br-sm bg-primary text-primary-foreground" : failed ? "rounded-bl-sm bg-amber-50 text-amber-900" : "rounded-bl-sm border border-ai-border bg-background"
        }`}
      >
        <span className="sr-only">{you ? "You: " : "AI: "}</span>
        {children}
      </p>
    </div>
  )
}

function TemplateBar({
  c,
  purpose,
  subject,
  body,
  invoiceNumbers,
  name,
}: {
  c: CaseDetail
  purpose: string
  subject: string
  body: string
  invoiceNumbers: string[] | null
  name: string
}) {
  const template = useEmailTemplate(c.id)
  const save = useSaveTemplate()
  const remove = useDeleteTemplate()
  const saved = template.data
  return (
    <div className="flex flex-wrap items-center gap-2 pt-1 text-xs">
      <span className="text-muted-foreground">
        {saved
          ? `${name}'s saved template is used for every new draft (updated ${formatDateTime(saved.updated_at)}${saved.updated_by ? ` by ${saved.updated_by}` : ""}).`
          : `No saved template for ${name} yet.`}
      </span>
      <Button
        type="button"
        size="sm"
        className="h-7 px-2 text-xs"
        variant="outline"
        disabled={save.isPending || !subject.trim() || !body.trim()}
        onClick={() =>
          void attempt(
            () => save.mutateAsync({ caseId: c.id, purpose, subject, body, invoice_numbers: invoiceNumbers }),
            `Saved as ${name}'s template: new drafts for them start from it.`,
          )
        }
      >
        <BookmarkPlus /> {saved ? "Replace template with this email" : `Save as ${name}'s template`}
      </Button>
      {saved && (
        <Button
          type="button"
          size="sm"
          className="h-7 px-2 text-xs"
          variant="ghost"
          disabled={remove.isPending}
          onClick={() => void attempt(() => remove.mutateAsync(c.id), "Template removed.")}
        >
          <Trash2 /> Remove template
        </Button>
      )}
    </div>
  )
}
