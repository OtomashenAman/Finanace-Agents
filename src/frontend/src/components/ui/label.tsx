import * as React from "react"

import { cn } from "@/lib/utils"

function Label({ className, ...props }: React.ComponentProps<"label">) {
  return (
    <label
      className={cn("block text-xs font-semibold tracking-wide text-muted-foreground uppercase", className)}
      {...props}
    />
  )
}

export { Label }
