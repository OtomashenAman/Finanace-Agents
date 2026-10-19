import type { AdminControls } from "../api"

export function AdminControlsCard({ controls }: { controls: AdminControls }) {
  const rows = [
    ["Entity", controls.entity],
    ["Period", controls.period_label],
    ["Review SLA", `${controls.review_sla_hours} hours`],
    ["Connector health", controls.connector_health],
    ["Model execution", controls.model_execution],
  ]

  return (
    <section className="rounded-lg border bg-card p-5 sm:p-6" aria-labelledby="admin-controls-title">
      <h2 id="admin-controls-title" className="border-b pb-4 text-lg font-semibold text-brand-navy">
        Finance Admin Controls
      </h2>
      <dl className="mt-2 space-y-4 pt-3">
        {rows.map(([label, value]) => (
          <div key={label} className="flex gap-1.5 text-[15px]">
            <dt className="text-muted-foreground">• {label}:</dt>
            <dd>{value}</dd>
          </div>
        ))}
      </dl>
    </section>
  )
}
