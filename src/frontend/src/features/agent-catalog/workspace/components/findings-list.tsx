import { CircleCheck, Info, OctagonAlert, TriangleAlert, type LucideIcon } from "lucide-react"

import { cn } from "@/lib/utils"

import type { Calculation, Flag, FlagSeverity } from "../api"
import { formatMoney } from "../format"

const STYLE: Record<FlagSeverity, { icon: LucideIcon; box: string; icon_tone: string; label: string }> = {
  pass: { icon: CircleCheck, box: "border-border bg-secondary/50", icon_tone: "text-emerald-600", label: "Passed" },
  info: { icon: Info, box: "border-blue-200 bg-blue-50", icon_tone: "text-blue-700", label: "Info" },
  warning: { icon: TriangleAlert, box: "border-amber-200 bg-amber-50", icon_tone: "text-amber-700", label: "Warning" },
  high: { icon: OctagonAlert, box: "border-red-200 bg-red-50", icon_tone: "text-red-700", label: "Exception" },
}

const ORDER: FlagSeverity[] = ["high", "warning", "info", "pass"]

export function FindingsList({ flags }: { flags: Flag[] }) {
  const sorted = [...flags].sort((a, b) => ORDER.indexOf(a.severity) - ORDER.indexOf(b.severity))
  return (
    <ul className="space-y-2.5">
      {sorted.map((flag) => {
        const { icon: Icon, box, icon_tone, label } = STYLE[flag.severity]
        return (
          <li key={flag.code} className={cn("flex items-start gap-3 rounded-lg border px-4 py-3", box)}>
            <Icon className={cn("mt-0.5 size-4 shrink-0", icon_tone)} aria-hidden />
            <span className="sr-only">{label}:</span>
            <span className={cn("text-[15px]", flag.severity !== "pass" && "font-medium")}>{flag.message}</span>
          </li>
        )
      })}
    </ul>
  )
}

export function CalculationsTable({ calculations }: { calculations: Calculation[] }) {
  return (
    <table className="w-full text-sm">
      <caption className="sr-only">Calculations</caption>
      <tbody className="divide-y">
        {calculations.map((c) => (
          <tr key={c.key}>
            <th scope="row" className="py-2 pr-4 text-left font-normal text-muted-foreground">
              {c.label}
            </th>
            <td className="py-2 text-right font-medium tabular-nums">
              {c.kind === "money" ? formatMoney(c.value) : (c.value ?? "—")}
              {c.kind === "percent" && c.value !== null && "%"}
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  )
}
