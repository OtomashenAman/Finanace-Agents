import { useEffect, useState } from "react"
import { useSearchParams } from "react-router"
import { CircleCheck, Database, Landmark, LoaderCircle, Upload } from "lucide-react"

import { AppPage } from "@/components/layout/app-page"
import { Alert } from "@/components/ui/alert"
import { Button } from "@/components/ui/button"
import { useCurrentUser } from "@/features/auth/hooks"
import { isAdmin } from "@/features/auth/roles"
import { errorMessage } from "@/lib/api"

import { SourceCard } from "./components/source-card"
import { UploadWizard } from "./components/upload-wizard"
import { useAuthorizeQuickBooks, useDataSources, useQuickBooksStatus } from "./hooks"

type Banner = { kind: "success" | "error"; text: string }

function bannerFrom(params: URLSearchParams): Banner | null {
  const result = params.get("quickbooks")
  if (!result) return null
  return result === "connected"
    ? { kind: "success", text: "QuickBooks is connected and your data was synced." }
    : { kind: "error", text: params.get("message") ?? "QuickBooks authorization failed." }
}

/** Intuit sends the browser back here with ?quickbooks=connected|error (see the API callback) */
function useOAuthResult(): [Banner | null, () => void] {
  const [params, setParams] = useSearchParams()
  const [banner, setBanner] = useState(() => bannerFrom(params))

  // Shown once: drop the parameters so a refresh doesn't repeat the message
  useEffect(() => {
    if (params.has("quickbooks")) setParams({}, { replace: true })
  }, [params, setParams])

  return [banner, () => setBanner(null)]
}

export function DataSourcesPage() {
  const { data: user } = useCurrentUser()
  const sources = useDataSources()
  const quickbooks = useQuickBooksStatus()
  const authorize = useAuthorizeQuickBooks()
  const [uploading, setUploading] = useState(false)
  const [banner, dismiss] = useOAuthResult()

  const qbReady = quickbooks.data?.configured === true

  return (
    <AppPage
      title="Data Sources"
      subtitle="Connect your own QuickBooks company or upload finance data. Agents use it to prefill and check your runs; only you can see it."
    >
      <div className="space-y-6">
        {banner &&
          (banner.kind === "success" ? (
            <div
              role="status"
              className="flex items-start justify-between gap-3 rounded-md border border-emerald-200 bg-emerald-50 px-3.5 py-3 text-sm text-emerald-800"
            >
              <span className="flex items-center gap-2">
                <CircleCheck className="size-4 shrink-0" aria-hidden />
                {banner.text}
              </span>
              <button type="button" onClick={dismiss} className="text-xs underline">
                Dismiss
              </button>
            </div>
          ) : (
            <Alert>{banner.text}</Alert>
          ))}

        <div className="flex flex-wrap items-center gap-3">
          <Button
            type="button"
            onClick={() => authorize.mutate(undefined)}
            disabled={!qbReady || authorize.isPending}
          >
            {authorize.isPending ? <LoaderCircle className="animate-spin" aria-hidden /> : <Landmark aria-hidden />}
            Connect QuickBooks
          </Button>
          <Button type="button" variant="outline" onClick={() => setUploading(true)} disabled={uploading}>
            <Upload aria-hidden />
            Upload file
          </Button>
          {quickbooks.data && !qbReady && (
            <p className="text-sm text-muted-foreground">
              {isAdmin(user)
                ? "Set up the QuickBooks app under Admin Settings → Integrations to enable connecting."
                : "QuickBooks isn't set up yet: ask your Finance Admin. You can still upload files."}
            </p>
          )}
          {quickbooks.data?.environment === "sandbox" && (
            <span className="rounded bg-amber-50 px-2 py-0.5 text-xs font-medium text-amber-800">
              QuickBooks sandbox
            </span>
          )}
        </div>
        {authorize.error && <Alert>{errorMessage(authorize.error, "Couldn't start the QuickBooks connection.")}</Alert>}

        {uploading && <UploadWizard onDone={() => setUploading(false)} />}

        {sources.isPending && (
          <div className="flex justify-center py-16" role="status">
            <LoaderCircle className="size-6 animate-spin text-primary" aria-hidden />
            <span className="sr-only">Loading data sources…</span>
          </div>
        )}
        {sources.isError && <Alert>Couldn't load your data sources. Refresh the page to try again.</Alert>}
        {sources.data?.length === 0 && !uploading && (
          <div className="flex flex-col items-center gap-2 rounded-lg border border-dashed bg-card px-6 py-16 text-center">
            <Database className="size-8 text-muted-foreground" aria-hidden />
            <p className="font-semibold">No data sources yet</p>
            <p className="max-w-md text-sm text-muted-foreground">
              Connect QuickBooks to bring in vendors, bills, purchase orders and your chart of accounts, or upload
              the same data as CSV/XLSX.
            </p>
          </div>
        )}
        {sources.data && sources.data.length > 0 && (
          <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
            {sources.data.map((source) => (
              <SourceCard key={source.id} source={source} />
            ))}
          </div>
        )}
      </div>
    </AppPage>
  )
}
