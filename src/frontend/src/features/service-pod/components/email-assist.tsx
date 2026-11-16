import { useState } from "react"
import { BookmarkPlus, Sparkles, Trash2 } from "lucide-react"

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

interface EmailAssistProps {
  c: CaseDetail
  purpose: string
  subject: string
  body: string
  onChange: (subject: string, body: string) => void
}

/** Ask the AI in plain English to write or change the email (the invoice table stays as the
 *  source gives it), and keep this customer's format as their template for every new draft. */
export function EmailAssist({ c, purpose, subject, body, onChange }: EmailAssistProps) {
  const assist = useAssist()
  const [ask, setAsk] = useState("")
  const customer = (c.state as { customer?: { id?: string; name?: string } }).customer
  const run = (instruction: string) =>
    void attempt(
      () => assist.mutateAsync({ caseId: c.id, purpose, instruction, subject, body }),
      "AI draft ready: check it before saving. The invoice table is unchanged.",
    ).then((r) => {
      if (!r) return
      onChange(r.subject, r.body)
      setAsk("")
    })

  return (
    <div className="space-y-2 rounded-lg border border-ai-border bg-ai-soft/50 p-2.5">
      <p className="flex flex-wrap items-center gap-1.5 text-xs text-ai-foreground">
        <AiBadge label="AI assist" />
        {body.trim() ? "Change this draft" : "Describe the email you want"} in plain English. Figures always come from the source.
      </p>
      <div className="flex flex-wrap gap-1.5">
        {body.trim() &&
          QUICK.map(([label, instruction]) => (
            <Button key={label} type="button" size="sm" className="h-7 px-2 text-xs" variant="outline" disabled={assist.isPending} onClick={() => run(instruction)}>
              {label}
            </Button>
          ))}
      </div>
      <div className="flex gap-2">
        <Input
          value={ask}
          onChange={(e) => setAsk(e.target.value)}
          placeholder={
            body.trim()
              ? "e.g. mention we can share timesheets, ask for a call this week"
              : "e.g. a polite first reminder asking when they'll pay"
          }
          onKeyDown={(e) => {
            if (e.key === "Enter" && ask.trim().length > 1) {
              e.preventDefault()
              run(ask.trim())
            }
          }}
          aria-label="Ask the AI"
        />
        <Button type="button" size="sm" disabled={assist.isPending || ask.trim().length < 2} onClick={() => run(ask.trim())}>
          <Sparkles /> {assist.isPending ? "Writing…" : "Ask AI"}
        </Button>
      </div>
      {customer?.id && <TemplateBar c={c} purpose={purpose} subject={subject} body={body} name={customer.name ?? "this customer"} />}
    </div>
  )
}

function TemplateBar({ c, purpose, subject, body, name }: { c: CaseDetail; purpose: string; subject: string; body: string; name: string }) {
  const template = useEmailTemplate(c.id)
  const save = useSaveTemplate()
  const remove = useDeleteTemplate()
  const saved = template.data
  return (
    <div className="flex flex-wrap items-center gap-2 border-t border-ai-border/60 pt-2 text-xs">
      <span className="text-muted-foreground">
        {saved
          ? `${name}'s saved template is used for every new draft (updated ${formatDateTime(saved.updated_at)}${saved.updated_by ? ` by ${saved.updated_by}` : ""}).`
          : `No saved template for ${name} yet.`}
      </span>
      <Button
        type="button"
        size="sm" className="h-7 px-2 text-xs"
        variant="outline"
        disabled={save.isPending || !subject.trim() || !body.trim()}
        onClick={() =>
          void attempt(
            () => save.mutateAsync({ caseId: c.id, purpose, subject, body }),
            `Saved as ${name}'s template: new drafts for them start from it.`,
          )
        }
      >
        <BookmarkPlus /> {saved ? "Replace template with this draft" : `Save as ${name}'s template`}
      </Button>
      {saved && (
        <Button
          type="button"
          size="sm" className="h-7 px-2 text-xs"
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
