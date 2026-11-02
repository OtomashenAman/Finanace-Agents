import { useState, type FormEvent } from "react"
import { LoaderCircle, Server } from "lucide-react"
import { toast } from "sonner"

import { Alert } from "@/components/ui/alert"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { errorMessage } from "@/lib/api"

import type { IntegrationEnvironment } from "../api"
import { useConnectErpNext } from "../hooks"

const SELECT =
  "flex h-10 w-full rounded-md border border-input bg-background px-3 text-sm focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/20 focus-visible:outline-none"

/** An ERPNext site for the Finance POD: an API user's key and secret and the company to read.
 *  The key is checked against the site before anything is saved; the secret is never shown again. */
export function ErpNextForm({ onDone }: { onDone: () => void }) {
  const connect = useConnectErpNext()
  const [name, setName] = useState("ERPNext")
  const [baseUrl, setBaseUrl] = useState("")
  const [company, setCompany] = useState("")
  const [apiKey, setApiKey] = useState("")
  const [apiSecret, setApiSecret] = useState("")
  const [environment, setEnvironment] = useState<IntegrationEnvironment>("sandbox")

  const onSubmit = (e: FormEvent) => {
    e.preventDefault()
    connect.mutate(
      {
        name: name.trim(),
        base_url: baseUrl.trim(),
        company: company.trim(),
        api_key: apiKey.trim(),
        api_secret: apiSecret.trim(),
        environment,
      },
      {
        onSuccess: (source) => {
          const n = Object.values(source.record_counts).reduce((a, b) => a + (b ?? 0), 0)
          toast.success(`${source.name} connected`, {
            description: `Company ${source.external_id}: ${n.toLocaleString()} records synced`,
          })
          onDone()
        },
      },
    )
  }

  return (
    <form onSubmit={onSubmit} className="space-y-4" aria-label="Connect ERPNext">
      {connect.error && <Alert>{errorMessage(connect.error, "Couldn't connect to ERPNext.")}</Alert>}
      <div className="grid gap-4 sm:grid-cols-2">
        <div className="space-y-1.5">
          <Label htmlFor="erp-name">Name</Label>
          <Input id="erp-name" value={name} onChange={(e) => setName(e.target.value)} maxLength={200} required />
        </div>
        <div className="space-y-1.5">
          <Label htmlFor="erp-url">ERPNext address</Label>
          <Input
            id="erp-url"
            value={baseUrl}
            onChange={(e) => setBaseUrl(e.target.value)}
            placeholder="https://erp.example.com"
            maxLength={500}
            required
          />
        </div>
        <div className="space-y-1.5">
          <Label htmlFor="erp-company">Company (exact name)</Label>
          <Input
            id="erp-company"
            value={company}
            onChange={(e) => setCompany(e.target.value)}
            placeholder="GIA Demo Labs"
            maxLength={100}
            required
          />
        </div>
        <div className="space-y-1.5">
          <Label htmlFor="erp-env">Data</Label>
          <select
            id="erp-env"
            className={SELECT}
            value={environment}
            onChange={(e) => setEnvironment(e.target.value as IntegrationEnvironment)}
          >
            <option value="sandbox">Demo / test data (snapshots labelled demo)</option>
            <option value="production">Real books</option>
          </select>
        </div>
        <div className="space-y-1.5">
          <Label htmlFor="erp-key">API key</Label>
          <Input id="erp-key" value={apiKey} onChange={(e) => setApiKey(e.target.value)} autoComplete="off" required />
        </div>
        <div className="space-y-1.5">
          <Label htmlFor="erp-secret">API secret</Label>
          <Input
            id="erp-secret"
            type="password"
            value={apiSecret}
            onChange={(e) => setApiSecret(e.target.value)}
            autoComplete="new-password"
            required
          />
        </div>
      </div>
      <p className="text-xs text-muted-foreground">
        In ERPNext open the integration user (User → API Access → Generate Keys). The local demo site prints its key with{" "}
        <code>uv run poe erpnext-seed --new-keys</code>; from the app running in Docker use{" "}
        <code>http://host.docker.internal:8090</code>.
      </p>
      <div className="flex gap-2">
        <Button type="submit" disabled={connect.isPending}>
          {connect.isPending ? <LoaderCircle className="animate-spin" aria-hidden /> : <Server aria-hidden />}
          Connect
        </Button>
        <Button type="button" variant="ghost" onClick={onDone}>
          Cancel
        </Button>
      </div>
    </form>
  )
}
