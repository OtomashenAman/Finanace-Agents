import { useState, type FormEvent } from "react"
import { Check, Copy, LoaderCircle } from "lucide-react"
import { toast } from "sonner"

import { AppPage } from "@/components/layout/app-page"
import { Alert } from "@/components/ui/alert"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Panel } from "@/features/agent-catalog/workspace/components/panel"
import { formatDateTime } from "@/features/agent-catalog/workspace/format"
import type { IntegrationApp, IntegrationEnvironment } from "@/features/data-sources/api"
import { StatusPill } from "@/features/data-sources/components/source-card"
import { useAllSources, useIntegration, useSetIntegration } from "@/features/data-sources/hooks"
import { errorMessage } from "@/lib/api"

import { AdminTabs } from "./components/admin-tabs"
import { Field } from "./components/form-bits"

const SELECT =
  "flex h-11 w-full rounded-md border border-input bg-background px-3 text-[15px] focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/20 focus-visible:outline-none"

function CopyField({ value }: { value: string }) {
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
      <Input id="redirect-uri" readOnly value={value} className="font-mono text-sm" onFocus={(e) => e.target.select()} />
      <Button type="button" variant="outline" onClick={() => void copy()} aria-label="Copy redirect URI">
        {copied ? <Check aria-hidden /> : <Copy aria-hidden />}
      </Button>
    </div>
  )
}

function QuickBooksAppForm({ app }: { app: IntegrationApp }) {
  const save = useSetIntegration()
  const [clientId, setClientId] = useState(app.client_id ?? "")
  const [clientSecret, setClientSecret] = useState("")
  const [environment, setEnvironment] = useState<IntegrationEnvironment>(app.environment)
  const secretRequired = !app.has_client_secret

  const onSubmit = (e: FormEvent) => {
    e.preventDefault()
    if (!clientId.trim() || (secretRequired && !clientSecret.trim())) return
    save.mutate(
      { client_id: clientId.trim(), environment, ...(clientSecret.trim() ? { client_secret: clientSecret.trim() } : {}) },
      {
        onSuccess: () => {
          setClientSecret("")
          toast.success("QuickBooks app saved", { description: "Users can now connect their own companies." })
        },
      },
    )
  }

  return (
    <Panel title="QuickBooks Online app">
      <form onSubmit={onSubmit} className="space-y-5" aria-label="QuickBooks app">
        <ol className="list-decimal space-y-1.5 pl-5 text-sm text-muted-foreground">
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
            , create an app with the <span className="font-mono text-xs">com.intuit.quickbooks.accounting</span> scope.
          </li>
          <li>Under Keys &amp; OAuth, add the Redirect URI below exactly as shown.</li>
          <li>Paste the Client ID and Client Secret here. Each user then connects their own company.</li>
        </ol>

        {save.error && <Alert>{errorMessage(save.error, "Couldn't save the QuickBooks app.")}</Alert>}

        <Field id="redirect-uri" label="Redirect URI" hint="Set PUBLIC_BASE_URL on the server if this isn't how users reach the app.">
          <CopyField value={app.redirect_uri} />
        </Field>
        <div className="grid gap-5 sm:grid-cols-2">
          <Field id="qb-client-id" label="Client ID">
            <Input id="qb-client-id" value={clientId} onChange={(e) => setClientId(e.target.value)} autoComplete="off" required />
          </Field>
          <Field
            id="qb-client-secret"
            label="Client Secret"
            hint={app.has_client_secret ? "Stored encrypted. Leave empty to keep it." : "Stored encrypted, never shown again."}
          >
            <Input
              id="qb-client-secret"
              type="password"
              value={clientSecret}
              onChange={(e) => setClientSecret(e.target.value)}
              autoComplete="new-password"
              placeholder={app.has_client_secret ? "••••••••" : ""}
              required={secretRequired}
            />
          </Field>
          <Field id="qb-environment" label="Environment" hint="Sandbox for Intuit test companies; Production for real books.">
            <select
              id="qb-environment"
              className={SELECT}
              value={environment}
              onChange={(e) => setEnvironment(e.target.value as IntegrationEnvironment)}
            >
              <option value="sandbox">Sandbox</option>
              <option value="production">Production</option>
            </select>
          </Field>
        </div>
        <div className="flex flex-wrap items-center gap-4 border-t pt-5">
          <Button type="submit" disabled={save.isPending}>
            {save.isPending && <LoaderCircle className="animate-spin" aria-hidden />}
            {app.configured ? "Save changes" : "Enable QuickBooks"}
          </Button>
          {app.updated_at && <span className="text-xs text-muted-foreground">Last changed {formatDateTime(app.updated_at)}</span>}
        </div>
      </form>
    </Panel>
  )
}

function AllSources() {
  const { data: sources, isPending, isError } = useAllSources()
  return (
    <Panel title="Users' data sources">
      <p className="mb-4 text-sm text-muted-foreground">
        Status only: each user's records and credentials stay private to them.
      </p>
      {isPending && <LoaderCircle className="size-5 animate-spin text-primary" aria-label="Loading" />}
      {isError && <Alert>Couldn't load data sources.</Alert>}
      {sources?.length === 0 && <p className="text-sm text-muted-foreground">No user has connected or uploaded data yet.</p>}
      {sources && sources.length > 0 && (
        <div className="overflow-x-auto">
          <table className="w-full min-w-[560px] text-sm">
            <thead>
              <tr className="border-b text-left text-xs tracking-wide text-muted-foreground uppercase">
                <th className="py-2 pr-4 font-semibold">User</th>
                <th className="py-2 pr-4 font-semibold">Source</th>
                <th className="py-2 pr-4 font-semibold">Last synced</th>
                <th className="py-2 font-semibold">Status</th>
              </tr>
            </thead>
            <tbody className="divide-y">
              {sources.map((s) => (
                <tr key={s.id}>
                  <td className="py-3 pr-4">
                    <p className="font-medium">{s.owner.full_name}</p>
                    <p className="text-xs text-muted-foreground">{s.owner.email}</p>
                  </td>
                  <td className="py-3 pr-4">
                    {s.name}
                    <p className="text-xs text-muted-foreground">{s.kind === "quickbooks" ? "QuickBooks" : "Upload"}</p>
                  </td>
                  <td className="py-3 pr-4">{formatDateTime(s.last_synced_at)}</td>
                  <td className="py-3">
                    <StatusPill source={s} />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </Panel>
  )
}

export function IntegrationsPage() {
  const { data: app, isPending, isError } = useIntegration()
  return (
    <AppPage title="Admin Settings · Integrations" subtitle="Set up QuickBooks once for the organization and see how users' connections are doing.">
      <AdminTabs />
      <div className="grid items-start gap-6 xl:grid-cols-2">
        {isPending && <LoaderCircle className="size-6 animate-spin text-primary" aria-label="Loading" />}
        {isError && <Alert>Couldn't load the integration settings.</Alert>}
        {app && <QuickBooksAppForm key={app.updated_at ?? "new"} app={app} />}
        <AllSources />
      </div>
    </AppPage>
  )
}
