import { useRef, useState } from "react"
import { Link } from "react-router"
import { Activity, CircleCheck, Send, TriangleAlert, Upload, Users } from "lucide-react"

import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Card, Empty, Field, LoadError, Loading, Pill } from "@/features/service-pod/components/bits"
import { formatDateTime } from "@/features/service-pod/labels"
import { attempt } from "@/features/service-pod/ui"

import { clientsApi } from "./clients-api"
import { FpodPage } from "./components/fpod-page"
import { useClientApplications, useClients, useFpodMutation } from "./hooks"
import { APPLICATION_STATUS, formatDate, RISK, termsText } from "./labels"

function Invite() {
  const invite = useFpodMutation(clientsApi.invite)
  const [name, setName] = useState("")
  const [email, setEmail] = useState("")
  const [link, setLink] = useState<string | null>(null)
  return (
    <Card
      title="Open a client account"
      hint="the onboarding agent emails the client a secure, single-use application link: company and tax details, contacts, the terms they'd like, and their documents."
    >
      <div className="flex flex-wrap items-end gap-2">
        <div className="min-w-56 flex-1">
          <Field label="Client name">
            <Input value={name} onChange={(e) => setName(e.target.value)} />
          </Field>
        </div>
        <div className="min-w-56 flex-1">
          <Field label="Client email">
            <Input type="email" value={email} onChange={(e) => setEmail(e.target.value)} />
          </Field>
        </div>
        <Button
          disabled={invite.isPending || !name.trim() || !email.trim()}
          onClick={async () => {
            const a = await attempt(() => invite.mutateAsync([name.trim(), email.trim()]), "Application link sent.")
            if (a) {
              setLink(a.portal_url)
              setName("")
              setEmail("")
            }
          }}
        >
          <Send aria-hidden /> Send application link
        </Button>
      </div>
      {link && (
        <p className="mt-3 rounded-md bg-muted/40 px-3 py-2 text-xs break-all">
          Link sent (shown once, for testing with the outbox): <a className="text-primary underline" href={link}>{link}</a>
        </p>
      )}
    </Card>
  )
}

function Applications() {
  const list = useClientApplications()
  const open = (list.data ?? []).filter((a) => a.status !== "active")
  return (
    <Card title="Applications" hint="Open applications; approved ones become accounts below.">
      {list.isPending ? (
        <Loading what="applications" />
      ) : list.isError ? (
        <LoadError what="applications" />
      ) : open.length === 0 ? (
        <Empty icon={<Users className="size-5" />}>No application is open.</Empty>
      ) : (
        <ul className="divide-y divide-border/60 text-sm">
          {open.map((a) => (
            <li key={a.id} className="flex flex-wrap items-center justify-between gap-2 py-2">
              <span>
                <Link to={`/finance-pod/clients/applications/${a.id}`} className="font-medium text-primary hover:underline">
                  {a.client_name}
                </Link>{" "}
                <span className="text-xs text-muted-foreground">{a.reference}</span>
                <span className="block text-xs text-muted-foreground">
                  {a.client_email}
                  {a.invited_at && ` · link sent ${formatDateTime(a.invited_at)}`}
                  {a.submitted_at && ` · applied ${formatDateTime(a.submitted_at)}`}
                </span>
              </span>
              <span className="flex items-center gap-2">
                {a.status === "submitted" && a.open_issues ? <Pill label={`${a.open_issues} to check`} tone="warn" /> : null}
                {a.risk && <Pill label={RISK[a.risk][0]} tone={RISK[a.risk][1]} />}
                <Pill label={APPLICATION_STATUS[a.status][0]} tone={APPLICATION_STATUS[a.status][1]} />
              </span>
            </li>
          ))}
        </ul>
      )}
    </Card>
  )
}

function Accounts() {
  const list = useClients()
  const monitor = useFpodMutation(clientsApi.monitor)
  const history = useFpodMutation(clientsApi.importHistory)
  const input = useRef<HTMLInputElement>(null)
  return (
    <Card
      title="Client accounts"
      hint="Created once by the account agent in the ERP and the lab system. Terms change only by the credit controller's approval."
      actions={
        <div className="flex flex-wrap gap-2">
          <Input
            ref={input}
            type="file"
            accept=".csv,.xlsx"
            className="hidden"
            onChange={async (e) => {
              const file = e.target.files?.[0]
              e.target.value = ""
              if (file)
                await attempt(
                  () => history.mutateAsync([file]),
                  (r) =>
                    `${r.rows} invoice(s) imported${r.skipped.length ? `, ${r.skipped.length} skipped` : ""}. Monitor: ${r.monitor.proposed} review(s) proposed.`,
                )
            }}
          />
          <Button size="sm" variant="outline" disabled={history.isPending} onClick={() => input.current?.click()} title="CSV or XLSX: Client, Invoice, Amount, Issued, Due, Paid">
            <Upload aria-hidden /> Import billing history
          </Button>
          <Button
            size="sm"
            variant="outline"
            disabled={monitor.isPending}
            onClick={() =>
              attempt(
                () => monitor.mutateAsync([]),
                (r) => `Monitor reviewed ${r.reviewed} account(s): ${r.proposed} review(s) proposed, ${r.resynced} lab record(s) corrected.`,
              )
            }
          >
            <Activity aria-hidden /> Run the monitor
          </Button>
        </div>
      }
    >
      {list.isPending ? (
        <Loading what="client accounts" />
      ) : list.isError ? (
        <LoadError what="client accounts" />
      ) : list.data.length === 0 ? (
        <Empty>No client account yet.</Empty>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead className="text-left text-xs text-muted-foreground">
              <tr className="border-b border-border">
                <th className="py-2 pr-3 font-medium">Account</th>
                <th className="py-2 pr-3 font-medium">Terms</th>
                <th className="py-2 pr-3 font-medium">Paid on time</th>
                <th className="py-2 pr-3 font-medium">ERP · lab system</th>
                <th className="py-2 font-medium">Next review</th>
              </tr>
            </thead>
            <tbody>
              {list.data.map((c) => (
                <tr key={c.id} className="border-b border-border/60 align-top hover:bg-muted/30">
                  <td className="py-2 pr-3">
                    <Link to={`/finance-pod/clients/${c.id}`} className="font-medium text-primary hover:underline">
                      {c.code} {c.name}
                    </Link>
                    <span className="mt-0.5 flex gap-1">
                      {c.status === "on_hold" && <Pill label="On hold" tone="bad" />}
                      {c.risk && <Pill label={RISK[c.risk][0]} tone={RISK[c.risk][1]} />}
                      {c.open_review_id && <Pill label="Review waiting" tone="warn" />}
                    </span>
                  </td>
                  <td className="py-2 pr-3">{termsText(c, c.currency)}</td>
                  <td className="py-2 pr-3 tabular-nums">
                    {c.history.on_time_rate === null ? "—" : `${Math.round(c.history.on_time_rate * 100)}%`}
                    <span className="block text-xs text-muted-foreground">{c.history.invoices} invoice(s)</span>
                  </td>
                  <td className="py-2 pr-3">
                    {c.sync.in_sync ? (
                      <span className="flex items-center gap-1 text-emerald-700">
                        <CircleCheck className="size-4" aria-hidden /> In sync
                      </span>
                    ) : (
                      <span className="flex items-center gap-1 text-amber-800">
                        <TriangleAlert className="size-4" aria-hidden /> Out of line
                      </span>
                    )}
                  </td>
                  <td className="py-2">{formatDate(c.next_review_on)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </Card>
  )
}

export function ClientsPage() {
  return (
    <FpodPage
      title="Client accounts"
      subtitle="The client applies; the onboarding agent checks; the credit agent proposes; the credit controller approves; the account agent sets up once."
    >
      <div className="space-y-5">
        <Invite />
        <Applications />
        <Accounts />
      </div>
    </FpodPage>
  )
}
