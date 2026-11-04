import { toast } from "sonner"

import { errorMessage } from "@/lib/api"

export const selectClass =
  "flex h-10 w-full rounded-md border border-input bg-background px-3 text-sm focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/20 focus-visible:outline-none"

/** Run a mutation and toast the outcome (the server's own message on failure). */
export async function attempt<T>(
  run: () => Promise<T>,
  success: string | ((result: T) => string),
  failure = "That didn't work.",
): Promise<T | undefined> {
  try {
    const result = await run()
    toast.success(typeof success === "function" ? success(result) : success)
    return result
  } catch (error) {
    toast.error(errorMessage(error, failure))
    return undefined
  }
}
