import { useState } from "react"
import { FileText, LoaderCircle, Send } from "lucide-react"
import { toast } from "sonner"

import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Card } from "@/features/service-pod/components/bits"
import { errorMessage } from "@/lib/api"

import type { StatementRun } from "../api"
import { useDraftStatements, useSendStatements } from "../hooks"

const thisMonth = new Date().toISOString().slice(0, 7)

/** Billing analyst: the month's client statements, drafted and then sent in one batch. */
export function StatementsCard() {
  const [month, setMonth] = useState(thisMonth)
  const [last, setLast] = useState<StatementRun | null>(null)
  const draft = useDraftStatements()
  const send = useSendStatements()
  const busy = draft.isPending || send.isPending
  const report = (verb: string) => (r: StatementRun) => {
    setLast(r)
    const n = verb === "Drafted" ? r.drafted.length : r.sent.length
    toast.success(`${verb} ${n} statement(s)`)
  }
  return (
    <Card title="Monthly statements" hint="Each client with an invoice sent this month gets its open items on one statement. Draft them, read them under each case's Mail, then send all.">
      <div className="flex flex-wrap items-end gap-2">
        <label className="space-y-1 text-sm">
          <span className="font-medium">Month</span>
          <Input type="month" value={month} onChange={(e) => setMonth(e.target.value)} className="w-44" />
        </label>
        <Button size="sm" variant="outline" disabled={busy || !month}
          onClick={() => draft.mutate(month, { onSuccess: report("Drafted"), onError: (e) => toast.error(errorMessage(e, "Couldn't draft")) })}>
          {draft.isPending ? <LoaderCircle className="size-4 animate-spin" aria-hidden /> : <FileText className="size-4" aria-hidden />}
          Draft statements
        </Button>
        <Button size="sm" disabled={busy || !month}
          onClick={() => send.mutate(month, { onSuccess: report("Sent"), onError: (e) => toast.error(errorMessage(e, "Couldn't send")) })}>
          {send.isPending ? <LoaderCircle className="size-4 animate-spin" aria-hidden /> : <Send className="size-4" aria-hidden />}
          Send all drafted
        </Button>
      </div>
      {last && (
        <ul className="mt-3 space-y-1 text-sm">
          {last.drafted.length > 0 && <li>Drafted for: {last.drafted.join(", ")}</li>}
          {last.sent.length > 0 && <li>Sent to: {last.sent.join(", ")}</li>}
          {last.skipped.map((s) => <li key={s} className="text-muted-foreground">Skipped {s}</li>)}
          {last.drafted.length + last.sent.length + last.skipped.length === 0 && (
            <li className="text-muted-foreground">Nothing waits for a statement.</li>
          )}
        </ul>
      )}
    </Card>
  )
}
