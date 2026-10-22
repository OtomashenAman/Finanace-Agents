import { LoaderCircle } from "lucide-react"

import { Button } from "@/components/ui/button"

export function FullPageSpinner() {
  return (
    <div className="flex min-h-svh items-center justify-center bg-brand-page" role="status">
      <LoaderCircle className="size-7 animate-spin text-primary" aria-hidden />
      <span className="sr-only">Loading…</span>
    </div>
  )
}

export function FullPageError({ message, onRetry }: { message: string; onRetry: () => void }) {
  return (
    <div className="flex min-h-svh flex-col items-center justify-center gap-4 bg-brand-page px-4 text-center">
      <p className="text-foreground">{message}</p>
      <Button onClick={onRetry}>Try again</Button>
    </div>
  )
}
