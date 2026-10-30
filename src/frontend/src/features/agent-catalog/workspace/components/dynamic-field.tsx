import type { UseFormRegister } from "react-hook-form"

import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Textarea } from "@/components/ui/textarea"
import { cn } from "@/lib/utils"

import type { FormField } from "../api"

export type FormValues = Record<string, string | boolean>

interface DynamicFieldProps {
  field: FormField
  register: UseFormRegister<FormValues>
  error?: string
  disabled?: boolean
}

/** Renders one input from the backend's form spec; the same component serves every agent. */
export function DynamicField({ field, register, error, disabled }: DynamicFieldProps) {
  const id = `field-${field.name}`
  const describedBy = [error && `${id}-error`, field.help && `${id}-help`].filter(Boolean).join(" ") || undefined
  const a11y = { id, disabled, "aria-invalid": error ? true : undefined, "aria-describedby": describedBy }

  if (field.kind === "boolean") {
    return (
      <div className="flex items-center gap-2.5 pt-6">
        <input type="checkbox" className="size-4 accent-primary" {...a11y} {...register(field.name)} />
        <label htmlFor={id} className="text-sm font-medium text-brand-navy">
          {field.label}
        </label>
      </div>
    )
  }

  return (
    <div className={cn("space-y-1.5", field.kind === "textarea" && "sm:col-span-2")}>
      <Label htmlFor={id} className="text-sm font-semibold tracking-normal text-brand-navy normal-case">
        {field.label}
        {!field.required && <span className="ml-1 font-normal text-muted-foreground">(optional)</span>}
      </Label>
      {field.kind === "textarea" ? (
        <Textarea maxLength={field.max_length ?? undefined} {...a11y} {...register(field.name)} />
      ) : (
        <div className="relative">
          <Input
            type="text"
            inputMode={field.kind === "text" ? undefined : "decimal"}
            autoComplete="off"
            placeholder={field.kind === "money" ? "0.00" : "Enter value"}
            maxLength={field.max_length ?? undefined}
            className={cn(field.kind === "money" && "tabular-nums", field.kind === "percent" && "pr-9")}
            {...a11y}
            {...register(field.name)}
          />
          {field.kind === "percent" && (
            <span className="pointer-events-none absolute inset-y-0 right-3 flex items-center text-sm text-muted-foreground">
              %
            </span>
          )}
        </div>
      )}
      {field.help && !error && (
        <p id={`${id}-help`} className="text-xs text-muted-foreground">
          {field.help}
        </p>
      )}
      {error && (
        <p id={`${id}-error`} className="text-sm text-destructive">
          {error}
        </p>
      )}
    </div>
  )
}
