import { useRef, useState } from "react"
import { Link } from "react-router"
import { Download, RefreshCw, Send, Upload } from "lucide-react"

import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Card, Empty, Field, LoadError, Loading, Pill } from "@/features/service-pod/components/bits"
import { formatDateTime } from "@/features/service-pod/labels"
import { attempt } from "@/features/service-pod/ui"

import { FpodPage } from "./components/fpod-page"
import { useFpodMutation, useOnboardings, useSanctions } from "./hooks"
import { ONBOARDING_STATUS } from "./labels"
import { procurementApi } from "./procurement-api"

function Invite() {
  const invite = useFpodMutation(procurementApi.invite)
  const change = useFpodMutation(procurementApi.bankChange)
  const [name, setName] = useState("")
  const [email, setEmail] = useState("")
  const [code, setCode] = useState("")
  const [link, setLink] = useState<string | null>(null)
  return (
    <Card
      title="Onboard a vendor"
      hint="the onboarding agent emails a secure, single-use portal link. Bank details are only ever taken there, never by email."
    >
      <div className="grid gap-4 lg:grid-cols-2">
        <div className="space-y-2">
          <div className="grid gap-2 sm:grid-cols-2">
            <Field label="Vendor name">
              <Input value={name} onChange={(e) => setName(e.target.value)} />
            </Field>
            <Field label="Vendor email">
              <Input type="email" value={email} onChange={(e) => setEmail(e.target.value)} />
            </Field>
          </div>
          <Button
            size="sm"
            disabled={invite.isPending || !name.trim() || !email.trim()}
            onClick={async () => {
              const ob = await attempt(() => invite.mutateAsync([name.trim(), email.trim()]), "Portal link sent.")
              if (ob) {
                setLink(ob.portal_url)
                setName("")
                setEmail("")
              }
            }}
          >
            <Send aria-hidden /> Send portal link
          </Button>
        </div>
        <div className="space-y-2">
          <Field label="Bank change for an existing vendor (vendor code)" hint="The vendor re-enters the new details on the portal; same checks, call-back and second approver.">
            <Input value={code} onChange={(e) => setCode(e.target.value)} placeholder="e.g. V-LAB" />
          </Field>
          <Button
            size="sm"
            variant="outline"
            disabled={change.isPending || !code.trim()}
            onClick={async () => {
              const ob = await attempt(() => change.mutateAsync([code.trim(), null]), "Bank-change portal link sent.")
              if (ob) {
                setLink(ob.portal_url)
                setCode("")
              }
            }}
          >
            <Send aria-hidden /> Send bank-change link
          </Button>
        </div>
      </div>
      {link && (
        <p className="mt-3 rounded-md bg-muted/40 px-3 py-2 text-xs break-all">
          Link sent (shown once, for testing with the outbox): <a className="text-primary underline" href={link}>{link}</a>
        </p>
      )}
    </Card>
  )
}

function Sanctions() {
  const info = useSanctions()
  const refresh = useFpodMutation(procurementApi.refreshSanctions)
  const input = useRef<HTMLInputElement>(null)
  return (
    <Card
      title="Sanctions list (OFAC SDN)"
      hint="The onboarding agent screens every vendor against it. With no list loaded, screening fails rather than passing."
      actions={
        <div className="flex gap-2">
          <Button size="sm" variant="outline" disabled={refresh.isPending} onClick={() => attempt(() => refresh.mutateAsync([undefined]), "Sanctions list downloaded.")}>
            <RefreshCw aria-hidden /> Download latest
          </Button>
          <Input
            ref={input}
            type="file"
            accept=".csv"
            className="hidden"
            onChange={async (e) => {
              const file = e.target.files?.[0]
              e.target.value = ""
              if (file) await attempt(() => refresh.mutateAsync([file]), "Sanctions list loaded.")
            }}
          />
          <Button size="sm" variant="outline" disabled={refresh.isPending} onClick={() => input.current?.click()}>
            <Upload aria-hidden /> Upload sdn.csv
          </Button>
        </div>
      }
    >
      {info.isPending ? (
        <Loading what="the sanctions list" />
      ) : info.isError ? (
        <LoadError what="the sanctions list" />
      ) : info.data.entries ? (
        <p className="text-sm">
          {info.data.entries.toLocaleString()} entries, loaded {formatDateTime(info.data.loaded_at!)}.
        </p>
      ) : (
        <p className="text-sm text-amber-800">No list loaded yet: vendors can't pass screening until it is.</p>
      )}
    </Card>
  )
}

export function VendorsPage() {
  const list = useOnboardings()
  return (
    <FpodPage title="Vendors" subtitle="Onboard new vendor: the onboarding agent reads and checks; the AP analyst verifies; a second approver activates.">
      <div className="space-y-5">
        <Invite />
        <Card title="Onboardings">
          {list.isPending ? (
            <Loading what="onboardings" />
          ) : list.isError ? (
            <LoadError what="onboardings" />
          ) : list.data.length === 0 ? (
            <Empty>No vendor is being onboarded.</Empty>
          ) : (
            <ul className="divide-y divide-border/60 text-sm">
              {list.data.map((o) => (
                <li key={o.id} className="flex flex-wrap items-center justify-between gap-2 py-2">
                  <span>
                    <Link to={`/finance-pod/vendors/${o.id}`} className="font-medium text-primary hover:underline">
                      {o.vendor_name}
                    </Link>{" "}
                    {o.kind === "bank_change" && <Pill label="bank change" tone="warn" />}
                    <span className="block text-xs text-muted-foreground">
                      {o.vendor_email}
                      {o.vendor_code && ` · ${o.vendor_code}`}
                      {o.request_reference && ` · for ${o.request_reference}`}
                      {o.invited_at && ` · invited ${formatDateTime(o.invited_at)}`}
                    </span>
                  </span>
                  <span className="flex items-center gap-2">
                    {o.open_issues ? <Pill label={`${o.open_issues} to resolve`} tone="warn" /> : null}
                    <Pill label={ONBOARDING_STATUS[o.status][0]} tone={ONBOARDING_STATUS[o.status][1]} />
                  </span>
                </li>
              ))}
            </ul>
          )}
        </Card>
        <Sanctions />
        <p className="text-xs text-muted-foreground">
          <Download className="mr-1 inline size-3" aria-hidden />
          Vendors become active in the vendor master here (local ERP). Workday is used once its connection is set up.
        </p>
      </div>
    </FpodPage>
  )
}
