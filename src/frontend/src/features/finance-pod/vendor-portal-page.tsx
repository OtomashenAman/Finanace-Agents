import { useState, type FormEvent } from "react"
import { useParams } from "react-router"
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { CircleCheck, LoaderCircle, ShieldCheck, Upload } from "lucide-react"

import { Alert } from "@/components/ui/alert"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { errorMessage } from "@/lib/api"

import { portalApi } from "./api"

const NAMES: Record<string, string> = {
  tax_form: "Tax form (W-9, or W-8BEN / W-8BEN-E outside the US)",
  bank_letter: "Bank letter confirming the account, on the bank's letterhead",
  compliance: "Insurance or compliance papers",
}

/** The vendor's secure upload page: no account, only the signed link from the invitation. */
export function VendorPortalPage() {
  const { token = "" } = useParams()
  const client = useQueryClient()
  const view = useQuery({ queryKey: ["vendor-portal", token], queryFn: () => portalApi.view(token), retry: false })
  const upload = useMutation({
    mutationFn: portalApi.upload,
    onSuccess: () => void client.invalidateQueries({ queryKey: ["vendor-portal", token] }),
  })
  const [kind, setKind] = useState("tax_form")
  const [file, setFile] = useState<File | null>(null)

  const submit = (e: FormEvent) => {
    e.preventDefault()
    if (file) upload.mutate({ token, kind, file }, { onSuccess: () => setFile(null) })
  }

  return (
    <main className="mx-auto min-h-screen max-w-xl px-4 py-10">
      <div className="mb-6 flex items-center gap-2 text-brand-navy">
        <ShieldCheck className="size-6" aria-hidden />
        <h1 className="text-xl font-semibold">Supplier set-up</h1>
      </div>
      {view.isLoading && <LoaderCircle className="size-6 animate-spin text-primary" aria-label="Loading" />}
      {view.isError && <Alert>{errorMessage(view.error, "This link isn't valid any more. Ask your contact for a new one.")}</Alert>}
      {view.data && (
        <div className="space-y-5">
          <p className="text-sm">
            Please upload the documents below for <span className="font-semibold">{view.data.vendor_name}</span>. This page works until{" "}
            {new Date(view.data.expires_at).toLocaleDateString()}. We never ask for bank details by email.
          </p>
          <ul className="space-y-2 text-sm">
            {[...view.data.required, ...view.data.optional].map((k) => {
              const done = view.data.uploaded.filter((u) => u.kind === k)
              return (
                <li key={k} className="flex items-start gap-2">
                  <CircleCheck className={`mt-0.5 size-4 shrink-0 ${done.length ? "text-emerald-600" : "text-muted-foreground"}`} aria-hidden />
                  <span>
                    {NAMES[k]}
                    {view.data.optional.includes(k) && " (if any)"}
                    {done.map((d) => (
                      <span key={d.filename + d.uploaded_at} className="block text-xs text-muted-foreground">
                        {d.filename} · {new Date(d.uploaded_at).toLocaleString()}
                      </span>
                    ))}
                  </span>
                </li>
              )
            })}
          </ul>
          <form onSubmit={submit} className="space-y-3 rounded-lg border p-4">
            {upload.error && <Alert>{errorMessage(upload.error, "Upload failed")}</Alert>}
            <select aria-label="Document" className="flex h-10 w-full rounded-md border border-input bg-background px-3 text-sm"
              value={kind} onChange={(e) => setKind(e.target.value)}>
              {Object.entries(NAMES).map(([k, n]) => <option key={k} value={k}>{n}</option>)}
            </select>
            <Input type="file" aria-label="File" accept=".pdf,.png,.jpg,.jpeg,.txt,.docx"
              onChange={(e) => setFile(e.target.files?.[0] ?? null)} />
            <Button type="submit" disabled={!file || upload.isPending}>
              {upload.isPending ? <LoaderCircle className="animate-spin" aria-hidden /> : <Upload aria-hidden />} Upload
            </Button>
          </form>
        </div>
      )}
    </main>
  )
}
