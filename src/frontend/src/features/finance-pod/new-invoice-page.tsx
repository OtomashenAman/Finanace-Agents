import { useNavigate } from "react-router"

import { Card } from "@/features/service-pod/components/bits"
import { attempt } from "@/features/service-pod/ui"

import { FpodPage } from "./components/fpod-page"
import { InvoiceForm } from "./components/invoice-form"
import { useFinanceSettings, useFpodMutation } from "./hooks"
import { invoicesApi } from "./invoices-api"

/** An invoice keyed by hand (no document to read). */
export function NewInvoicePage() {
  const navigate = useNavigate()
  const create = useFpodMutation(invoicesApi.create)
  const settings = useFinanceSettings()
  return (
    <FpodPage title="Key an invoice" subtitle="Without a document to read. It's saved as captured; post it from its page.">
      <Card title="Invoice">
        <InvoiceForm
          key={settings.data?.currency ?? "USD"}
          initial={{
            vendor_code: null,
            vendor_invoice_number: null,
            invoice_date: new Date().toISOString().slice(0, 10),
            due_date: null,
            currency: settings.data?.currency ?? "USD",
            tax_code: null,
            tax_total: "0",
            total: null,
            po_reference: null,
            lines: [{ description: "", quantity: "1", unit_price: "", po_line: null }],
          }}
          saving={create.isPending}
          submitLabel="Save invoice"
          onSubmit={async (body) => {
            const inv = await attempt(() => create.mutateAsync([body]), (r) => `${r.reference} saved.`)
            if (inv) navigate(`/finance-pod/invoices/${inv.id}`)
          }}
        />
      </Card>
    </FpodPage>
  )
}
