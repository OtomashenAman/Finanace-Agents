import { useState } from "react"
import { Headset } from "lucide-react"

import { Alert } from "@/components/ui/alert"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Textarea } from "@/components/ui/textarea"
import { errorMessage } from "@/lib/api"

import { paymentsApi } from "./payments-api"

/** Vendors' self-service help: no login; the answer goes to the email we hold for them. */
export function VendorHelpPage() {
  const [email, setEmail] = useState("")
  const [number, setNumber] = useState("")
  const [question, setQuestion] = useState("")
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [done, setDone] = useState<string | null>(null)

  const submit = async () => {
    setBusy(true)
    setError(null)
    try {
      const r = await paymentsApi.help(email, number || null, question)
      setDone(`${r.message} (Reference ${r.reference}.)`)
    } catch (err) {
      setError(errorMessage(err, "Your question couldn't be sent. Try again."))
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="min-h-svh bg-brand-page px-3 py-8">
      <div className="mx-auto max-w-lg rounded-2xl border border-border bg-card p-6 shadow-sm">
        <p className="flex items-center gap-2 text-xs font-medium text-muted-foreground">
          <Headset className="size-4" aria-hidden /> Supplier help
        </p>
        <h1 className="mt-2 text-xl font-semibold">Ask about an invoice or a payment</h1>
        <p className="mt-1 text-sm text-muted-foreground">
          Payment status, whether we received your invoice, or a disagreement. Answers are sent to the email address we
          hold for your company.
        </p>
        {done ? (
          <p className="mt-5 rounded-lg bg-emerald-50 px-3 py-3 text-sm text-emerald-900">{done}</p>
        ) : (
          <div className="mt-5 space-y-3">
            <div className="space-y-1">
              <Label htmlFor="email">Your company email (the one we pay you from records)</Label>
              <Input id="email" type="email" value={email} onChange={(e) => setEmail(e.target.value)} />
            </div>
            <div className="space-y-1">
              <Label htmlFor="number">Invoice number (if it's about one)</Label>
              <Input id="number" value={number} onChange={(e) => setNumber(e.target.value)} />
            </div>
            <div className="space-y-1">
              <Label htmlFor="question">Your question</Label>
              <Textarea id="question" rows={4} value={question} onChange={(e) => setQuestion(e.target.value)} />
            </div>
            {error && <Alert>{error}</Alert>}
            <Button className="w-full" disabled={busy || !email || question.trim().length < 5} onClick={() => void submit()}>
              {busy ? "Sending…" : "Send"}
            </Button>
          </div>
        )}
      </div>
    </div>
  )
}
