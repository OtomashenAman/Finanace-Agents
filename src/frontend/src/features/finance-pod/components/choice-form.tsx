import { useState, type FormEvent } from "react"

import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Textarea } from "@/components/ui/textarea"
import { selectClass } from "@/features/service-pod/ui"

import type { CaseDetail } from "../api"
import { useCaseCatalogue } from "../hooks"

interface QuoteRow {
  vendor_id: string | null
  vendor_name: string
  reference: string
  total: string
}

/** 1.3.2 Buyer chooses: an active vendor (or a new one, which opens its onboarding), the
 *  quote, the terms, and why when it isn't the cheapest. */
export function ChoiceForm({
  c,
  busy,
  onSubmit,
}: {
  c: CaseDetail
  busy: boolean
  onSubmit: (results: Record<string, Record<string, unknown>>) => void
}) {
  const catalogue = useCaseCatalogue(c.id)
  const comparison = c.steps.find((s) => s.key === "1.3.1.c")?.l5[0]?.result as
    | { quotes: QuoteRow[]; cheapest: string | null }
    | null
    | undefined
  const quotes = comparison?.quotes ?? []
  const [mode, setMode] = useState<"existing" | "new">("existing")
  const [vendor, setVendor] = useState("")
  const [quote, setQuote] = useState("")
  const [newName, setNewName] = useState("")
  const [newEmail, setNewEmail] = useState("")
  const [terms, setTerms] = useState("")
  const [reason, setReason] = useState("")
  const [reviewed, setReviewed] = useState(false)
  const notCheapest = Boolean(comparison?.cheapest) && quote !== comparison?.cheapest

  const submit = (e: FormEvent) => {
    e.preventDefault()
    onSubmit({
      "1.3.2.a": { reviewed: true },
      "1.3.2.b": {
        ...(mode === "existing" ? { vendor_id: vendor } : { new_vendor_name: newName, new_vendor_email: newEmail }),
        ...(quote ? { quote_reference: quote } : {}),
        terms,
        ...(reason ? { reason } : {}),
      },
    })
  }

  return (
    <form onSubmit={submit} className="space-y-3 rounded-md border border-border/70 bg-background/70 p-3">
      <label className="flex items-center gap-2 text-sm">
        <input type="checkbox" checked={reviewed} onChange={(e) => setReviewed(e.target.checked)} required />
        1.3.2.a · I reviewed the comparison
      </label>
      <p className="text-xs font-semibold text-muted-foreground">1.3.2.b · Confirms vendor and terms</p>
      <div className="flex gap-4 text-sm">
        {(["existing", "new"] as const).map((m) => (
          <label key={m} className="flex items-center gap-1.5">
            <input type="radio" name="vendor-mode" checked={mode === m} onChange={() => setMode(m)} />
            {m === "existing" ? "A vendor from the master" : "A new vendor (opens onboarding)"}
          </label>
        ))}
      </div>
      {mode === "existing" ? (
        <select aria-label="Vendor" className={selectClass} value={vendor} onChange={(e) => setVendor(e.target.value)} required>
          <option value="">Choose a vendor…</option>
          {catalogue.data?.vendors.map((v) => (
            <option key={v.id} value={v.id} disabled={v.detail !== "Active"}>
              {v.name}
              {v.detail !== "Active" ? ` (${v.detail})` : ""}
            </option>
          ))}
        </select>
      ) : (
        <div className="grid gap-2 sm:grid-cols-2">
          <Input aria-label="New vendor's name" placeholder="Vendor's legal name" value={newName}
            onChange={(e) => setNewName(e.target.value)} required />
          <Input aria-label="Contact email" type="email" placeholder="Their contact email" value={newEmail}
            onChange={(e) => setNewEmail(e.target.value)} required />
        </div>
      )}
      {quotes.length > 0 && (
        <select aria-label="Quote chosen" className={selectClass} value={quote} onChange={(e) => setQuote(e.target.value)}>
          <option value="">No quote (contract or catalogue price)</option>
          {quotes.map((q) => (
            <option key={q.reference} value={q.reference}>
              {q.reference} · {q.vendor_name} · {q.total}
              {q.reference === comparison?.cheapest ? " (cheapest)" : ""}
            </option>
          ))}
        </select>
      )}
      <Input aria-label="Terms agreed" placeholder="Terms agreed (e.g. net 30, delivery in 5 days)" value={terms}
        onChange={(e) => setTerms(e.target.value)} required minLength={2} />
      {notCheapest && (
        <Textarea aria-label="Why" rows={2} placeholder="Why not the cheapest quote?" value={reason}
          onChange={(e) => setReason(e.target.value)} required />
      )}
      <Button type="submit" size="sm" disabled={busy || !reviewed}>
        Confirm the choice
      </Button>
    </form>
  )
}
