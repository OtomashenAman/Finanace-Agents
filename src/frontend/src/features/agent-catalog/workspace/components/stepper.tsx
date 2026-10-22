import { Check } from "lucide-react"

import { cn } from "@/lib/utils"

export type Step = "input" | "result" | "review"

const STEPS: { id: Step; label: string }[] = [
  { id: "input", label: "Input" },
  { id: "result", label: "Result" },
  { id: "review", label: "Review" },
]

interface StepperProps {
  current: Step
  /** furthest step the run has reached */
  reached: Step
  onSelect: (step: Step) => void
}

/** Input · Result · Review, without numbering; reached steps can be revisited. */
export function Stepper({ current, reached, onSelect }: StepperProps) {
  const reachedIndex = STEPS.findIndex((s) => s.id === reached)
  return (
    <nav aria-label="Run steps">
      <ol className="flex flex-wrap items-center gap-2">
        {STEPS.map((step, index) => {
          const done = index < reachedIndex
          const available = index <= reachedIndex
          const active = step.id === current
          return (
            <li key={step.id} className="flex items-center gap-2">
              {index > 0 && <span className="h-px w-6 bg-border sm:w-10" aria-hidden />}
              <button
                type="button"
                disabled={!available}
                onClick={() => onSelect(step.id)}
                aria-current={active ? "step" : undefined}
                className={cn(
                  "flex items-center gap-2 rounded-full border px-3.5 py-1.5 text-sm font-medium transition-colors",
                  active && "border-primary bg-primary text-primary-foreground",
                  !active && available && "border-border bg-card text-brand-navy hover:border-primary/50",
                  !available && "cursor-not-allowed border-dashed text-muted-foreground",
                )}
              >
                {done && !active && <Check className="size-3.5 text-emerald-600" aria-hidden />}
                {step.label}
              </button>
            </li>
          )
        })}
      </ol>
    </nav>
  )
}
