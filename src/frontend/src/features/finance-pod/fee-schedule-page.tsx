import { useRef } from "react"
import { Download, Upload } from "lucide-react"

import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Card, Empty, LoadError, Loading } from "@/features/service-pod/components/bits"
import { attempt } from "@/features/service-pod/ui"

import { billingApi } from "./billing-api"
import { FpodPage } from "./components/fpod-page"
import { useFeeSchedule, useFpodMutation } from "./hooks"
import { formatDate, money } from "./labels"

const band = (from: string | null, to: string | null) =>
  from === null && to === null ? "any" : `${from === null ? "0" : Number(from)}${to === null ? "+" : `–${Number(to)}`} ct`

export function FeeSchedulePage() {
  const q = useFeeSchedule()
  const upload = useFpodMutation(billingApi.uploadFeeSchedule)
  const input = useRef<HTMLInputElement>(null)
  const s = q.data
  return (
    <FpodPage title="Fee schedule" subtitle="The published fees, contract prices and tax rates the fee-rule agent applies. Only an upload here changes them.">
      <div className="space-y-5">
        <Card
          title="Load the schedule"
          hint="One workbook with three sheets: Fees, Contract prices, Tax rates. An upload replaces all three, or nothing if any row is wrong."
          actions={
            <div className="flex flex-wrap gap-2">
              <Button size="sm" variant="outline" onClick={() => billingApi.downloadTemplate()}>
                <Download aria-hidden /> Template (with a demo schedule)
              </Button>
              <Input
                ref={input}
                type="file"
                accept=".xlsx"
                className="hidden"
                onChange={async (e) => {
                  const file = e.target.files?.[0]
                  e.target.value = ""
                  if (file) await attempt(() => upload.mutateAsync([file]), (r) => `Loaded ${r.fees.length} fees, ${r.contracts.length} contract prices, ${r.taxes.length} tax rates.`)
                }}
              />
              <Button size="sm" disabled={upload.isPending} onClick={() => input.current?.click()}>
                <Upload aria-hidden /> Upload workbook
              </Button>
            </div>
          }
        >
          {q.isPending ? (
            <Loading what="the fee schedule" />
          ) : q.isError || !s ? (
            <LoadError what="the fee schedule" />
          ) : s.fees.length === 0 ? (
            <Empty>No fee schedule loaded: invoices can't be priced until it is.</Empty>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead className="text-left text-xs text-muted-foreground">
                  <tr className="border-b border-border">
                    <th className="py-2 pr-3 font-medium">Service</th>
                    <th className="py-2 pr-3 font-medium">Stone</th>
                    <th className="py-2 pr-3 font-medium">Weight</th>
                    <th className="py-2 pr-3 font-medium">Turnaround</th>
                    <th className="py-2 text-right font-medium">Fee</th>
                  </tr>
                </thead>
                <tbody>
                  {s.fees.map((f, i) => (
                    <tr key={i} className="border-b border-border/60">
                      <td className="py-1.5 pr-3">
                        {f.service_name} <span className="text-xs text-muted-foreground">{f.service_code}</span>
                      </td>
                      <td className="py-1.5 pr-3">{f.stone_type ?? "any"}</td>
                      <td className="py-1.5 pr-3">{band(f.carat_from, f.carat_to)}</td>
                      <td className="py-1.5 pr-3 capitalize">{f.turnaround}</td>
                      <td className="py-1.5 text-right tabular-nums">{money(f.fee, f.currency)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </Card>
        {s && (
          <div className="grid gap-5 lg:grid-cols-2">
            <Card title="Contract prices">
              {s.contracts.length === 0 ? (
                <p className="text-sm text-muted-foreground">None.</p>
              ) : (
                <ul className="divide-y divide-border/60 text-sm">
                  {s.contracts.map((c) => (
                    <li key={`${c.client_code}-${c.service_code}`} className="flex justify-between py-1.5">
                      <span>
                        {c.client_code} · {c.service_code}
                        {c.contract_ref && <span className="text-xs text-muted-foreground"> · {c.contract_ref}</span>}
                      </span>
                      <span className="tabular-nums">
                        {c.price !== null ? money(c.price) : `${Number(c.discount_pct)}% off`}
                        {c.valid_to && <span className="text-xs text-muted-foreground"> until {formatDate(c.valid_to)}</span>}
                      </span>
                    </li>
                  ))}
                </ul>
              )}
            </Card>
            <Card title="Tax rates" hint="By the client's country, and US state from the client's address.">
              {s.taxes.length === 0 ? (
                <p className="text-sm text-muted-foreground">None: every invoice is flagged for its tax.</p>
              ) : (
                <ul className="divide-y divide-border/60 text-sm">
                  {s.taxes.map((t) => (
                    <li key={`${t.country}-${t.region}`} className="flex justify-between py-1.5">
                      <span>
                        {t.country}
                        {t.region ? ` · ${t.region}` : " (country-wide)"} · {t.name}
                      </span>
                      <span className="tabular-nums">{Number(t.rate_pct)}%</span>
                    </li>
                  ))}
                </ul>
              )}
            </Card>
          </div>
        )}
      </div>
    </FpodPage>
  )
}
