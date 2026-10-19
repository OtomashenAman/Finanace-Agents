import { cn } from "@/lib/utils"

interface KpiCardProps {
  label: string
  value: number
  tone?: "default" | "warning"
}

export function KpiCard({ label, value, tone = "default" }: KpiCardProps) {
  return (
    <div className="rounded-lg border bg-card px-5 py-5">
      <p
        className={cn("text-[2rem] leading-none font-bold tabular-nums", tone === "warning" ? "text-amber-700" : "text-primary")}
      >
        {value.toLocaleString()}
      </p>
      <p className="mt-3 text-sm text-muted-foreground">{label}</p>
    </div>
  )
}
