import { Inbox } from "lucide-react"

import { Card, Empty, LoadError, Loading } from "@/features/service-pod/components/bits"

import { useFinanceDashboard } from "./hooks"
import { FinancePage } from "./components/finance-page"
import { QueueRow } from "./components/queue-list"
import { QUEUE_META, QUEUE_ORDER } from "./labels"

/** Everything waiting on the viewer, grouped by what they do: decide, review, send, post,
 *  verify, run. Oldest first within each group. */
export function FinanceQueuePage() {
  const { data, isLoading, isError } = useFinanceDashboard()
  const items = data?.my_queue ?? []
  return (
    <FinancePage title="My queue" subtitle="What waits on you now, by what you do. Oldest first.">
      {isLoading && <Loading what="your queue" />}
      {isError && <LoadError what="your queue" />}
      {data && items.length === 0 && (
        <Card title="All clear">
          <Empty icon={<Inbox className="size-5" />}>Nothing waits on you right now.</Empty>
        </Card>
      )}
      <div className="space-y-4">
        {QUEUE_ORDER.map((type) => {
          const mine = items.filter((i) => i.type === type)
          if (mine.length === 0) return null
          return (
            <Card key={type} title={`${QUEUE_META[type].group} (${mine.length})`}>
              <ul className="divide-y divide-border/60">
                {mine.map((item) => (
                  <QueueRow key={`${item.type}-${item.case_id}-${item.step_key}-${item.step_title}`} item={item} />
                ))}
              </ul>
            </Card>
          )
        })}
      </div>
    </FinancePage>
  )
}
