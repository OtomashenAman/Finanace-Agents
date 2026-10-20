import { useState, type FormEvent } from "react"
import { Check, Copy, Landmark, LoaderCircle } from "lucide-react"
import { toast } from "sonner"

import { Alert } from "@/components/ui/alert"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { errorMessage } from "@/lib/api"

import type { DataSource, IntegrationEnvironment } from "../api"
import { useConnectQuickBooks, useRedirectUri, useUpdateApp } from "../hooks"

const SELECT =
  "flex h-10 w-full rounded-md border border-input bg-background px-3 text-sm focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/20 focus-visible:outline-none"

function CopyField({ id, value }: { id: string; value: string }) {
  const [copied, setCopied] = useState(false)
  const copy = async () => {
    try {
      await navigator.clipboard.writeText(value)
      setCopied(true)
      setTimeout(() => setCopied(false), 2000)
    } catch {
      toast.error("Couldn't copy: select the text and copy it manually")
    }
  }
  return (
    <div className="flex gap-2">
      <Input id={id} readOnly value={value} className="h-10 font-mono text-xs" onFocus={(e) => e.target.select()} />
      <Button type="button" variant="outline" className="h-10" onClick={() => void copy()} aria-label="Copy redirect URI">
        {copied ? <Check aria-hidden /> : <Copy aria-hidden />}
      </Button>
    </div>
  )
}

interface QuickBooksAppFormProps {
  /** Editing an existing connection's app; omitted: connect a new company */
  source?: DataSource
  onDone: () => void
}

/** The user's own Intuit app: every user connects with their own Client ID and Secret. */
export function QuickBooksAppForm({ source, onDone }: QuickBooksAppFormProps) {
  const redirect = useRedirectUri()
  const connect = useConnectQuickBooks()
  const update = useUpdateApp()
  const [clientId, setClientId] = useState(source?.client_id ?? "")
  const [clientSecret, setClientSecret] = useState("")
  const [environment, setEnvironment] = useState<IntegrationEnvironment>(source?.environment ?? "sandbox")
  const editing = source !== undefined
  const mutation = editing ? update : connect
  const prefix = editing ? `app-${source.id}` : "app-new"

  const onSubmit = (e: FormEvent) => {
    e.preventDefault()
    if (!clientId.trim() || (!editing && !clientSecret.trim())) return
    if (!editing) {
      connect.mutate({ client_id: clientId.trim(), client_secret: clientSecret.trim(), environment })
      return
    }
    update.mutate(
      {
        id: source.id,
        client_id: clientId.trim(),
        environment,
        ...(clientSecret.trim() ? { client_secret: clientSecret.trim() } : {}),
      },
      {
        onSuccess: (saved) => {
          toast.success(saved.status === "connected" ? "No changes" : "App updated: re-authorize to continue")
          onDone()
        },
      },
    )
  }

  return (
    <form onSubmit={onSubmit} className="space-y-4" aria-label={editing ? "QuickBooks app credentials" : "Connect QuickBooks"}>
      {!editing && (
        <ol className="list-decimal space-y-1 pl-5 text-sm text-muted-foreground">
          <li>
            In the{" "}
            <a
              href="https://developer.intuit.com/app/developer/myapps"
              target="_blank"
              rel="noreferrer"
              className="font-medium text-primary hover:underline"
            >
              Intuit Developer portal
            </a>
            , open (or create) your app with the Accounting scope.
          </li>
          <li>Under Keys &amp; OAuth, add the Redirect URI below exactly as shown.</li>
          <li>Paste your Client ID and Client Secret, then sign in to QuickBooks and pick your company.</li>
        </ol>
      )}

      {mutation.error && <Alert>{errorMessage(mutation.error, "Couldn't save the QuickBooks app.")}</Alert>}

      <div className="space-y-2">
        <Label htmlFor={`${prefix}-redirect`}>Redirect URI</Label>
        {redirect.data ? (
          <CopyField id={`${prefix}-redirect`} value={redirect.data.redirect_uri} />
        ) : (
          <LoaderCircle className="size-4 animate-spin text-primary" aria-label="Loading" />
        )}
      </div>
      <div className="grid gap-4 sm:grid-cols-3">
        <div className="space-y-2">
          <Label htmlFor={`${prefix}-id`}>Client ID</Label>
          <Input
            id={`${prefix}-id`}
            className="h-10 text-sm"
            value={clientId}
            onChange={(e) => setClientId(e.target.value)}
            autoComplete="off"
            required
          />
        </div>
        <div className="space-y-2">
          <Label htmlFor={`${prefix}-secret`}>Client Secret</Label>
          <Input
            id={`${prefix}-secret`}
            type="password"
            className="h-10 text-sm"
            value={clientSecret}
            onChange={(e) => setClientSecret(e.target.value)}
            autoComplete="new-password"
            placeholder={editing ? "Leave empty to keep" : ""}
            required={!editing}
          />
        </div>
        <div className="space-y-2">
          <Label htmlFor={`${prefix}-env`}>Environment</Label>
          <select
            id={`${prefix}-env`}
            className={SELECT}
            value={environment}
            onChange={(e) => setEnvironment(e.target.value as IntegrationEnvironment)}
          >
            <option value="sandbox">Sandbox</option>
            <option value="production">Production</option>
          </select>
        </div>
      </div>
      <p className="text-xs text-muted-foreground">
        Your secret is stored encrypted and never shown again. Only you can use this connection.
      </p>
      <div className="flex flex-wrap gap-3">
        <Button type="submit" size="sm" disabled={mutation.isPending}>
          {mutation.isPending ? <LoaderCircle className="animate-spin" aria-hidden /> : !editing && <Landmark aria-hidden />}
          {editing ? "Save app" : connect.isPending ? "Opening QuickBooks…" : "Continue to QuickBooks"}
        </Button>
        <Button type="button" size="sm" variant="outline" onClick={onDone} disabled={connect.isPending}>
          Cancel
        </Button>
      </div>
    </form>
  )
}
