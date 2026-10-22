import * as React from "react"
import { CircleAlert } from "lucide-react"

import { cn } from "@/lib/utils"

function Alert({ className, children, ...props }: React.ComponentProps<"div">) {
  return (
    <div
      role="alert"
      className={cn(
        "flex items-start gap-2.5 rounded-md border border-destructive/25 bg-destructive/5 px-3.5 py-3 text-sm text-destructive",
        className,
      )}
      {...props}
    >
      <CircleAlert className="mt-0.5 size-4 shrink-0" aria-hidden />
      <div>{children}</div>
    </div>
  )
}

export { Alert }
