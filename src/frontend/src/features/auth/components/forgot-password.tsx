import { useState, type FormEvent } from "react"
import { LoaderCircle } from "lucide-react"

import { Alert } from "@/components/ui/alert"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { errorMessage } from "@/lib/api"

import { useRequestReset } from "../hooks"

/** No email service: the request goes to the Finance Admins' worklist. */
export function ForgotPassword({ onDone }: { onDone: () => void }) {
  const request = useRequestReset()
  const [email, setEmail] = useState("")

  const onSubmit = (e: FormEvent) => {
    e.preventDefault()
    if (email.trim()) request.mutate(email.trim())
  }

  if (request.isSuccess) {
    return (
      <div className="space-y-4" role="status">
        <p className="text-sm">
          {request.data.message} They'll set a new password and share it with you securely.
        </p>
        <Button type="button" variant="outline" onClick={onDone}>
          Back to sign in
        </Button>
      </div>
    )
  }

  return (
    <form onSubmit={onSubmit} noValidate className="space-y-4" aria-label="Forgot password">
      <p className="text-sm text-muted-foreground">
        Enter your work email. A Finance Admin will be asked to set a new password for you.
      </p>
      {request.error && <Alert>{errorMessage(request.error, "Couldn't send the request.")}</Alert>}
      <div className="space-y-2">
        <Label htmlFor="reset-email">Work email</Label>
        <Input
          id="reset-email"
          type="email"
          autoComplete="username"
          value={email}
          onChange={(e) => setEmail(e.target.value)}
          placeholder="name@company.com"
          autoFocus
        />
      </div>
      <div className="flex gap-3">
        <Button type="submit" disabled={request.isPending || !email.trim()}>
          {request.isPending && <LoaderCircle className="animate-spin" aria-hidden />}
          Ask for a reset
        </Button>
        <Button type="button" variant="ghost" onClick={onDone}>
          Cancel
        </Button>
      </div>
    </form>
  )
}
