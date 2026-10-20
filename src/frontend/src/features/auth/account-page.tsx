import { useState, type FormEvent } from "react"
import { LoaderCircle } from "lucide-react"
import { toast } from "sonner"

import { AppPage } from "@/components/layout/app-page"
import { Alert } from "@/components/ui/alert"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Panel } from "@/features/agent-catalog/workspace/components/panel"
import { ApiError, errorMessage } from "@/lib/api"

import { useChangePassword, useCurrentUser } from "./hooks"
import { ROLE_LABELS } from "./roles"

const MIN = 12

function PasswordForm() {
  const change = useChangePassword()
  const [current, setCurrent] = useState("")
  const [next, setNext] = useState("")
  const [confirm, setConfirm] = useState("")
  const mismatch = confirm.length > 0 && confirm !== next
  const tooShort = next.length > 0 && next.length < MIN

  const onSubmit = (e: FormEvent) => {
    e.preventDefault()
    if (!current || next.length < MIN || next !== confirm) return
    change.mutate(
      { current_password: current, new_password: next },
      {
        onSuccess: () => {
          setCurrent("")
          setNext("")
          setConfirm("")
          toast.success("Password changed", { description: "Your other sessions were signed out." })
        },
      },
    )
  }

  const serverError =
    change.error instanceof ApiError && change.error.code === "wrong_password"
      ? "Your current password isn't correct."
      : change.error
        ? errorMessage(change.error, "Couldn't change the password.")
        : null

  return (
    <form onSubmit={onSubmit} noValidate className="max-w-md space-y-4" aria-label="Change password">
      {serverError && <Alert>{serverError}</Alert>}
      <div className="space-y-2">
        <Label htmlFor="pw-current">Current password</Label>
        <Input
          id="pw-current"
          type="password"
          autoComplete="current-password"
          value={current}
          onChange={(e) => setCurrent(e.target.value)}
        />
      </div>
      <div className="space-y-2">
        <Label htmlFor="pw-new">New password</Label>
        <Input
          id="pw-new"
          type="password"
          autoComplete="new-password"
          value={next}
          onChange={(e) => setNext(e.target.value)}
          aria-invalid={tooShort ? true : undefined}
        />
        <p className={tooShort ? "text-xs text-destructive" : "text-xs text-muted-foreground"}>
          At least {MIN} characters.
        </p>
      </div>
      <div className="space-y-2">
        <Label htmlFor="pw-confirm">Repeat the new password</Label>
        <Input
          id="pw-confirm"
          type="password"
          autoComplete="new-password"
          value={confirm}
          onChange={(e) => setConfirm(e.target.value)}
          aria-invalid={mismatch ? true : undefined}
        />
        {mismatch && <p className="text-xs text-destructive">The passwords don't match.</p>}
      </div>
      <Button type="submit" disabled={change.isPending || !current || next.length < MIN || next !== confirm}>
        {change.isPending && <LoaderCircle className="animate-spin" aria-hidden />}
        Change password
      </Button>
    </form>
  )
}

export function AccountPage() {
  const { data: user } = useCurrentUser()
  if (!user) return null
  return (
    <AppPage title="My account" subtitle="Your profile and password.">
      <div className="grid items-start gap-6 lg:grid-cols-2">
        <Panel title="Profile">
          <dl className="space-y-2 text-sm">
            {[
              ["Name", user.full_name],
              ["Email", user.email],
              ["Role", ROLE_LABELS[user.role]],
            ].map(([k, v]) => (
              <div key={k} className="grid grid-cols-[90px_minmax(0,1fr)]">
                <dt className="text-muted-foreground">{k}</dt>
                <dd className="font-medium">{v}</dd>
              </div>
            ))}
          </dl>
          <p className="mt-4 text-xs text-muted-foreground">A Finance Admin manages names, roles and access.</p>
        </Panel>
        <Panel title="Change password">
          <PasswordForm />
        </Panel>
      </div>
    </AppPage>
  )
}
