import { useRef, useState, type FormEvent, type ReactNode } from "react"
import { Database, Download, Upload } from "lucide-react"

import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Switch } from "@/components/ui/switch"
import { Card, Empty, Field, LoadError, Loading } from "@/features/service-pod/components/bits"
import { attempt, selectClass } from "@/features/service-pod/ui"

import { fpodApi, type DemoDataResult, type FinanceSettings, type ImportResult, type Reference } from "./api"
import { FpodPage } from "./components/fpod-page"
import { useFinanceSettings, useFpodMutation, useReference } from "./hooks"
import { formatDate, money } from "./labels"

function ReferenceUpload() {
  const upload = useFpodMutation(fpodApi.importReference)
  const input = useRef<HTMLInputElement>(null)
  const [result, setResult] = useState<ImportResult | null>(null)
  return (
    <Card
      title="Load reference data"
      hint="One workbook, any of its sheets. Rows are matched on their code and updated; rows not in the file stay (use the Active column to retire one). The authority matrix is replaced as a whole. All or nothing: any error and nothing changes."
      actions={
        <div className="flex gap-2">
          <Button size="sm" variant="outline" onClick={() => fpodApi.downloadTemplate()}>
            <Download aria-hidden /> Template
          </Button>
          <Input
            ref={input}
            type="file"
            accept=".xlsx"
            className="hidden"
            onChange={async (e) => {
              const file = e.target.files?.[0]
              e.target.value = ""
              if (!file) return
              const r = await attempt(() => upload.mutateAsync([file]), "Reference data loaded.")
              setResult(r ?? null)
            }}
          />
          <Button size="sm" disabled={upload.isPending} onClick={() => input.current?.click()}>
            <Upload aria-hidden /> {upload.isPending ? "Loading…" : "Upload workbook"}
          </Button>
        </div>
      }
    >
      {result ? (
        <div className="space-y-2 text-sm">
          <ul className="grid gap-1 sm:grid-cols-2">
            {result.sheets.map((s) => (
              <li key={s.sheet}>
                <strong>{s.title}</strong>: {s.created} new, {s.updated} changed
                {s.removed ? `, ${s.removed} replaced` : ""}
              </li>
            ))}
          </ul>
          {result.warnings.length > 0 && (
            <ul className="list-disc space-y-0.5 pl-5 text-amber-800 dark:text-amber-300">
              {result.warnings.map((w) => (
                <li key={w}>{w}</li>
              ))}
            </ul>
          )}
        </div>
      ) : (
        <p className="text-sm text-muted-foreground">
          Sheets: Cost centres, Labs, Projects, Grants, Budgets, Catalogue (contract prices), Vendors (approved list,
          never bank details), Authority matrix. Download the template for the columns.
        </p>
      )}
    </Card>
  )
}

function SettingsCard() {
  const settings = useFinanceSettings()
  if (settings.isPending) return <Loading what="settings" />
  if (settings.isError) return <LoadError what="settings" />
  return <SettingsForm key={settings.data.updated_at ?? "defaults"} saved={settings.data} />
}

function SettingsForm({ saved }: { saved: FinanceSettings }) {
  const save = useFpodMutation(fpodApi.saveSettings)
  const [form, setForm] = useState<Omit<FinanceSettings, "updated_at">>({
    currency: saved.currency,
    purchasing_threshold: saved.purchasing_threshold,
    min_quotes: saved.min_quotes,
    allow_self_approval: saved.allow_self_approval,
    price_tolerance_pct: saved.price_tolerance_pct,
    price_tolerance_amount: saved.price_tolerance_amount,
    qty_tolerance_pct: saved.qty_tolerance_pct,
    payment_horizon_days: saved.payment_horizon_days,
    cash_available: saved.cash_available,
    unusual_payment_amount: saved.unusual_payment_amount,
    bank_change_days: saved.bank_change_days,
    max_new_client_limit: saved.max_new_client_limit,
    credit_review_days: saved.credit_review_days,
    estimate_tolerance_pct: saved.estimate_tolerance_pct,
  })
  const submit = (e: FormEvent) => {
    e.preventDefault()
    const cash = form.cash_available?.trim() || null
    void attempt(() => save.mutateAsync([{ ...form, cash_available: cash, clear_cash_available: cash === null }]), "Settings saved.")
  }
  return (
    <Card title="Finance POD settings" hint="Business rules the agents and checks apply.">
      <form onSubmit={submit} className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <Field label="Currency">
          <select className={selectClass} value={form.currency} onChange={(e) => setForm({ ...form, currency: e.target.value })}>
            {["USD", "EUR", "GBP", "INR", "CAD", "AUD"].map((c) => (
              <option key={c}>{c}</option>
            ))}
          </select>
        </Field>
        <Field label="Purchasing threshold" hint="Quotes are required at or above it.">
          <Input
            inputMode="decimal"
            value={form.purchasing_threshold}
            onChange={(e) => setForm({ ...form, purchasing_threshold: e.target.value })}
          />
        </Field>
        <Field label="Quotes required">
          <Input
            type="number"
            min={1}
            max={10}
            value={form.min_quotes}
            onChange={(e) => setForm({ ...form, min_quotes: Number(e.target.value) })}
          />
        </Field>
        <Field label="Price tolerance (%)" hint="Invoice match: per line, over the PO price.">
          <Input inputMode="decimal" value={form.price_tolerance_pct} onChange={(e) => setForm({ ...form, price_tolerance_pct: e.target.value })} />
        </Field>
        <Field label="…or per unit (amount)" hint="Whichever of the two is larger applies.">
          <Input inputMode="decimal" value={form.price_tolerance_amount} onChange={(e) => setForm({ ...form, price_tolerance_amount: e.target.value })} />
        </Field>
        <Field label="Quantity tolerance (%)" hint="Over what was received and not yet invoiced.">
          <Input inputMode="decimal" value={form.qty_tolerance_pct} onChange={(e) => setForm({ ...form, qty_tolerance_pct: e.target.value })} />
        </Field>
        <Field label="Payment run looks ahead (days)" hint="Invoices due within this many days go in the next run.">
          <Input type="number" min={0} max={90} value={form.payment_horizon_days} onChange={(e) => setForm({ ...form, payment_horizon_days: Number(e.target.value) })} />
        </Field>
        <Field label="Cash available" hint="Each currency group must fit in it. Empty: not checked.">
          <Input inputMode="decimal" value={form.cash_available ?? ""} onChange={(e) => setForm({ ...form, cash_available: e.target.value })} />
        </Field>
        <Field label="Unusual payment above" hint="Payments over this are flagged for the reviewer.">
          <Input inputMode="decimal" value={form.unusual_payment_amount} onChange={(e) => setForm({ ...form, unusual_payment_amount: e.target.value })} />
        </Field>
        <Field label="Recent bank change (days)" hint="Bank details changed within this need an AP call-back first.">
          <Input type="number" min={0} max={365} value={form.bank_change_days} onChange={(e) => setForm({ ...form, bank_change_days: Number(e.target.value) })} />
        </Field>
        <Field label="New client credit cap" hint="The most credit the credit agent proposes for a new client. The controller may approve more.">
          <Input inputMode="decimal" value={form.max_new_client_limit} onChange={(e) => setForm({ ...form, max_new_client_limit: e.target.value })} />
        </Field>
        <Field label="Client review every (days)" hint="The monitor proposes a periodic review of each account's terms.">
          <Input type="number" min={30} max={1095} value={form.credit_review_days} onChange={(e) => setForm({ ...form, credit_review_days: Number(e.target.value) })} />
        </Field>
        <Field label="Above estimate (%)" hint="An invoice this much over the intake fee estimate goes to the billing analyst.">
          <Input inputMode="decimal" value={form.estimate_tolerance_pct} onChange={(e) => setForm({ ...form, estimate_tolerance_pct: e.target.value })} />
        </Field>
        <div className="space-y-1 text-sm">
          <span className="font-medium text-brand-navy">Self-approval</span>
          <label className="flex items-center gap-2">
            <Switch
              checked={form.allow_self_approval}
              onCheckedChange={(v: boolean) => setForm({ ...form, allow_self_approval: v })}
              aria-label="Allow self-approval"
            />
            {form.allow_self_approval ? "Allowed (marked in the audit trail)" : "Different admins required"}
          </label>
          <span className="block text-xs text-muted-foreground">
            Off: requester and budget owner, vendor verifier and activator, and whoever opens a client application and
            approves its credit must be different Finance Admins. Turn on only
            for a single-admin setup.
          </span>
        </div>
        <div className="sm:col-span-2 lg:col-span-4">
          <Button type="submit" size="sm" disabled={save.isPending}>
            {save.isPending ? "Saving…" : "Save settings"}
          </Button>
        </div>
      </form>
    </Card>
  )
}

function Table({ head, rows }: { head: string[]; rows: ReactNode[][] }) {
  if (rows.length === 0) return <Empty>Nothing loaded.</Empty>
  return (
    <div className="max-h-80 overflow-auto">
      <table className="w-full text-sm">
        <thead className="sticky top-0 bg-card text-left text-xs text-muted-foreground">
          <tr className="border-b border-border">
            {head.map((h) => (
              <th key={h} className="py-1.5 pr-3 font-medium">
                {h}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((r, i) => (
            <tr key={i} className="border-b border-border/50">
              {r.map((c, j) => (
                <td key={j} className="py-1.5 pr-3">
                  {c}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

const yes = (v: boolean) => (v ? "Yes" : "No")

function ReferenceTables({ d }: { d: Reference }) {
  const tabs: { key: string; label: string; table: ReactNode }[] = [
    {
      key: "cc",
      label: `Cost centres (${d.cost_centres.length})`,
      table: <Table head={["Code", "Name", "Budget owner", "Active"]} rows={d.cost_centres.map((c) => [c.code, c.name, c.owner_email ?? "—", yes(c.active)])} />,
    },
    {
      key: "labs",
      label: `Labs (${d.labs.length})`,
      table: <Table head={["Code", "Name", "Cost centre", "Active"]} rows={d.labs.map((c) => [c.code, c.name, c.cost_centre_code ?? "—", yes(c.active)])} />,
    },
    {
      key: "projects",
      label: `Projects (${d.projects.length})`,
      table: (
        <Table
          head={["Code", "Name", "Cost centre", "Grant", "Active"]}
          rows={d.projects.map((c) => [c.code, c.name, c.cost_centre_code ?? "—", c.grant_code ?? "—", yes(c.active)])}
        />
      ),
    },
    {
      key: "grants",
      label: `Grants (${d.grants.length})`,
      table: (
        <Table
          head={["Code", "Name", "Sponsor", "Period", "Award", "Not allowed"]}
          rows={d.grants.map((g) => [
            g.code,
            g.name,
            g.sponsor ?? "—",
            `${formatDate(g.start_date)} to ${formatDate(g.end_date)}`,
            money(g.award_amount),
            g.unallowable_categories.join(", ") || "—",
          ])}
        />
      ),
    },
    {
      key: "budgets",
      label: `Budgets (${d.budgets.length})`,
      table: (
        <Table
          head={["Year", "Cost centre / grant", "Category", "Budget", "Committed", "Spent", "Remaining"]}
          rows={d.budgets.map((b) => [
            b.fiscal_year,
            b.cost_centre_code ?? b.grant_code,
            b.category ?? "all",
            money(b.amount),
            money(b.committed),
            money(b.spent),
            <strong key="r">{money(b.remaining)}</strong>,
          ])}
        />
      ),
    },
    {
      key: "catalogue",
      label: `Catalogue (${d.catalogue.length})`,
      table: (
        <Table
          head={["Item", "Description", "Category", "Price", "Vendor", "Contract"]}
          rows={d.catalogue.map((c) => [
            c.item_code,
            c.description,
            c.category ?? "—",
            `${money(c.unit_price)}${c.unit ? ` / ${c.unit}` : ""}`,
            c.vendor_code ?? "—",
            c.contract_ref ? `${c.contract_ref}${c.contract_end ? ` to ${formatDate(c.contract_end)}` : ""}` : "—",
          ])}
        />
      ),
    },
    {
      key: "vendors",
      label: `Vendors (${d.vendors.length})`,
      table: (
        <Table
          head={["Code", "Name", "Email", "Tax ID", "Status", "Categories"]}
          rows={d.vendors.map((v) => [v.code, v.name, v.email ?? "—", v.tax_id ?? "—", v.status, v.categories.join(", ") || "—"])}
        />
      ),
    },
    {
      key: "authority",
      label: `Authority matrix (${d.authority.length})`,
      table: (
        <Table
          head={["Scope", "Cost centre", "From amount", "Approver", "Capacity"]}
          rows={d.authority.map((t) => [
            t.scope === "po" ? "Purchase order" : "Request",
            t.cost_centre_code ?? "any",
            money(t.min_amount),
            t.approver_email,
            t.capacity,
          ])}
        />
      ),
    },
  ]
  const [active, setActive] = useState(tabs[0].key)
  return (
    <Card title="Loaded reference data">
      <div className="mb-3 flex flex-wrap gap-1" role="tablist">
        {tabs.map((t) => (
          <button
            key={t.key}
            type="button"
            role="tab"
            aria-selected={active === t.key}
            onClick={() => setActive(t.key)}
            className={
              active === t.key
                ? "rounded-md bg-primary px-2.5 py-1 text-xs font-medium text-primary-foreground"
                : "rounded-md px-2.5 py-1 text-xs font-medium text-muted-foreground hover:bg-muted"
            }
          >
            {t.label}
          </button>
        ))}
      </div>
      {tabs.find((t) => t.key === active)?.table}
    </Card>
  )
}

/** Demo data for a fresh database (e.g. a new production deployment): no shell needed. */
function DemoData() {
  const load = useFpodMutation(fpodApi.loadDemoData)
  const [result, setResult] = useState<DemoDataResult | null>(null)
  return (
    <Card
      title="Demo data"
      hint="Reference data, vendors with bank accounts, issued POs, invoices ready to pay, client accounts with history, a fee schedule and lab submissions. Safe to run again: what's already there is left alone. No email is sent."
      actions={
        <Button
          size="sm"
          variant="outline"
          disabled={load.isPending}
          onClick={async () => {
            if (!window.confirm("Load the Finance POD demo data into this environment?")) return
            const r = await attempt(() => load.mutateAsync([]), (x) => (x.loaded.length ? `Loaded ${x.loaded.length} section(s).` : "Everything was already there."))
            if (r) setResult(r)
          }}
        >
          <Database aria-hidden /> {load.isPending ? "Loading…" : "Load demo data"}
        </Button>
      }
    >
      {result ? (
        <ul className="space-y-1 text-sm">
          {result.loaded.map((l) => (
            <li key={l} className="text-emerald-800">
              ✓ {l}
            </li>
          ))}
          {result.skipped.map((l) => (
            <li key={l} className="text-muted-foreground">
              Already there: {l}
            </li>
          ))}
          {result.notes.map((l) => (
            <li key={l} className="text-amber-800">
              {l}
            </li>
          ))}
        </ul>
      ) : (
        <p className="text-sm text-muted-foreground">For demos and testing. The person loading it is the requester and buyer; another Finance Admin is the approver.</p>
      )}
    </Card>
  )
}

export function SetupPage() {
  const reference = useReference()
  return (
    <FpodPage title="Reference data & settings" subtitle="What the Finance POD agents work from, and the business rules they apply.">
      <div className="space-y-5">
        <DemoData />
        <ReferenceUpload />
        <SettingsCard />
        {reference.isPending ? (
          <Loading what="reference data" />
        ) : reference.isError ? (
          <LoadError what="reference data" />
        ) : (
          <ReferenceTables d={reference.data} />
        )}
      </div>
    </FpodPage>
  )
}
