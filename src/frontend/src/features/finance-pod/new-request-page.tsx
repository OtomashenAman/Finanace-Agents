import { useState } from "react"
import { useNavigate } from "react-router"
import { toast } from "sonner"

import { Alert } from "@/components/ui/alert"
import { Card } from "@/features/service-pod/components/bits"
import { errorMessage } from "@/lib/api"

import { fpodApi, type RequestIn } from "./api"
import { FpodPage } from "./components/fpod-page"
import { DescribeNeed, RequestForm } from "./components/request-form"
import { emptyRequest } from "./request-draft"
import { useFinanceSettings, useFpodMutation, useReference } from "./hooks"

export function NewRequestPage() {
  const navigate = useNavigate()
  const reference = useReference()
  const settings = useFinanceSettings()
  const create = useFpodMutation(fpodApi.create)
  const [draft, setDraft] = useState<{ body: RequestIn; notes: string[]; n: number }>({
    body: emptyRequest(),
    notes: [],
    n: 0,
  })

  const save = async (body: RequestIn) => {
    try {
      const created = await create.mutateAsync([body])
      toast.success(`${created.reference} saved as a draft. The request agent has checked it.`)
      navigate(`/finance-pod/requests/${created.id}`)
    } catch (error) {
      toast.error(errorMessage(error, "Couldn't save the request."))
    }
  }

  return (
    <FpodPage title="New purchase request" subtitle="Capture the request: describe the need; the request agent enriches it.">
      <div className="space-y-5">
        <DescribeNeed onDraft={(body, notes) => setDraft((d) => ({ body, notes, n: d.n + 1 }))} />
        {draft.notes.length > 0 && (
          <Alert className="border-amber-300/70 bg-amber-50 text-amber-900">
            <p className="font-medium">Check these before saving:</p>
            <ul className="mt-1 list-disc pl-4">
              {draft.notes.map((n) => (
                <li key={n}>{n}</li>
              ))}
            </ul>
          </Alert>
        )}
        <Card title="Request" hint="Saved as a draft: nothing is sent until you submit it.">
          <RequestForm
            key={draft.n}
            initial={draft.body}
            reference={reference.data}
            currency={settings.data?.currency ?? "USD"}
            saving={create.isPending}
            submitLabel="Save draft"
            onSubmit={save}
            onCancel={() => navigate("/finance-pod/requests")}
          />
        </Card>
      </div>
    </FpodPage>
  )
}
