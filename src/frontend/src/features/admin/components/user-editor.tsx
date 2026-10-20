import { useState, type ReactNode } from "react"
import { useForm, useWatch } from "react-hook-form"
import { zodResolver } from "@hookform/resolvers/zod"
import { LoaderCircle, Trash2 } from "lucide-react"
import { toast } from "sonner"

import { Alert } from "@/components/ui/alert"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Switch } from "@/components/ui/switch"
import { Panel } from "@/features/agent-catalog/workspace/components/panel"
import { errorMessage } from "@/lib/api"
import { formatDateTime } from "@/features/agent-catalog/workspace/format"

import type { Assignment, ManagedUser } from "../api"
import { describedBy, roleHint } from "../form-utils"
import { useDeleteUser, useResetPassword, useSetAssignments, useUpdateUser } from "../hooks"
import {
  passwordSchema,
  PASSWORD_MIN_LENGTH,
  profileSchema,
  type PasswordValues,
  type ProfileValues,
} from "../schema"
import { AssignmentsEditor } from "./assignments-editor"
import { Field, RoleSelect } from "./form-bits"

interface EditorProps {
  user: ManagedUser
  /** The signed-in admin is editing their own account: no demote/deactivate/delete */
  isSelf: boolean
}

function Section({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section className="space-y-4 border-t pt-5 first:border-t-0 first:pt-0">
      <h3 className="text-sm font-semibold text-brand-navy">{title}</h3>
      {children}
    </section>
  )
}

function ProfileSection({ user, isSelf }: EditorProps) {
  const update = useUpdateUser()
  const setActive = useUpdateUser()
  const {
    register,
    handleSubmit,
    reset,
    control,
    formState: { errors, isDirty },
  } = useForm<ProfileValues>({
    resolver: zodResolver(profileSchema),
    values: { full_name: user.full_name, role: user.role },
    mode: "onTouched",
  })
  const role = useWatch({ control, name: "role" })

  const onSubmit = handleSubmit((values) =>
    update.mutate(
      { id: user.id, ...values },
      {
        onSuccess: (saved) => {
          reset({ full_name: saved.full_name, role: saved.role })
          toast.success("Profile saved")
        },
      },
    ),
  )

  const toggleActive = (isActive: boolean) =>
    setActive.mutate(
      { id: user.id, is_active: isActive },
      {
        onSuccess: () =>
          toast.success(isActive ? `${user.full_name} can sign in again` : `${user.full_name} deactivated and signed out`),
        onError: (error) => toast.error(errorMessage(error, "Couldn't change the account status.")),
      },
    )

  return (
    <Section title="Profile">
      <form onSubmit={onSubmit} noValidate className="space-y-4" aria-label="Profile">
        {update.error && <Alert>{errorMessage(update.error, "Couldn't save the profile.")}</Alert>}
        <div className="grid gap-4 sm:grid-cols-2">
          <Field id="edit-name" label="Full name" error={errors.full_name?.message}>
            <Input id="edit-name" {...describedBy("edit-name", errors.full_name?.message)} {...register("full_name")} />
          </Field>
          <Field
            id="edit-role"
            label="Role"
            hint={isSelf ? "You can't change your own role." : roleHint(role)}
          >
            <RoleSelect id="edit-role" disabled={isSelf} {...register("role")} />
          </Field>
        </div>
        <div className="flex flex-wrap items-center justify-between gap-4">
          <Button type="submit" size="sm" disabled={!isDirty || update.isPending}>
            {update.isPending && <LoaderCircle className="animate-spin" aria-hidden />}
            Save profile
          </Button>
          <label className="flex items-center gap-2.5 text-sm">
            <Switch
              checked={user.is_active}
              onCheckedChange={toggleActive}
              disabled={isSelf || setActive.isPending}
              aria-label={user.is_active ? "Deactivate account" : "Activate account"}
            />
            {user.is_active ? "Active" : "Inactive"}
          </label>
        </div>
      </form>
    </Section>
  )
}

function AccessSection({ user }: { user: ManagedUser }) {
  const save = useSetAssignments()
  const initial = user.assignments.map(({ agent_key, capacity }) => ({ agent_key, capacity }))
  const [assignments, setAssignments] = useState<Assignment[]>(initial)
  const [dirty, setDirty] = useState(false)

  const onChange = (value: Assignment[]) => {
    setAssignments(value)
    setDirty(true)
  }

  const onSave = () =>
    save.mutate(
      { id: user.id, assignments },
      {
        onSuccess: () => {
          setDirty(false)
          toast.success("Agent access saved")
        },
        onError: (error) => toast.error(errorMessage(error, "Couldn't save agent access.")),
      },
    )

  if (user.role === "finance_admin") {
    return (
      <Section title="Agent access">
        <p className="text-sm text-muted-foreground">
          Finance Admins can prepare and approve runs on every agent, so no assignments are needed.
        </p>
      </Section>
    )
  }

  return (
    <Section title="Agent access">
      <AssignmentsEditor value={assignments} onChange={onChange} disabled={save.isPending} />
      <Button type="button" size="sm" onClick={onSave} disabled={!dirty || save.isPending}>
        {save.isPending && <LoaderCircle className="animate-spin" aria-hidden />}
        Save agent access
      </Button>
    </Section>
  )
}

function PasswordSection({ user }: { user: ManagedUser }) {
  const resetPassword = useResetPassword()
  const {
    register,
    handleSubmit,
    reset,
    formState: { errors },
  } = useForm<PasswordValues>({
    resolver: zodResolver(passwordSchema),
    defaultValues: { password: "" },
    mode: "onTouched",
  })

  const onSubmit = handleSubmit(({ password }) =>
    resetPassword.mutate(
      { id: user.id, password },
      {
        onSuccess: () => {
          reset()
          toast.success("Password changed", {
            description: `${user.full_name} was signed out everywhere and must use the new password.`,
          })
        },
      },
    ),
  )

  return (
    <Section title="Password">
      <form onSubmit={onSubmit} noValidate className="space-y-4" aria-label="Reset password">
        {resetPassword.error && <Alert>{errorMessage(resetPassword.error, "Couldn't change the password.")}</Alert>}
        <Field
          id="edit-password"
          label="New password"
          error={errors.password?.message}
          hint={`At least ${PASSWORD_MIN_LENGTH} characters. Also unlocks the account and ends its sessions.`}
        >
          <Input
            id="edit-password"
            type="password"
            autoComplete="new-password"
            {...describedBy("edit-password", errors.password?.message)}
            {...register("password")}
          />
        </Field>
        <Button type="submit" size="sm" variant="secondary" disabled={resetPassword.isPending}>
          {resetPassword.isPending && <LoaderCircle className="animate-spin" aria-hidden />}
          Set new password
        </Button>
      </form>
    </Section>
  )
}

function DeleteSection({ user, onDeleted }: { user: ManagedUser; onDeleted: () => void }) {
  const remove = useDeleteUser()
  const [confirming, setConfirming] = useState(false)

  const onDelete = () =>
    remove.mutate(user.id, {
      onSuccess: () => {
        toast.success(`${user.full_name} deleted`)
        onDeleted()
      },
      onSettled: () => setConfirming(false),
    })

  return (
    <Section title="Delete user">
      <p className="text-sm text-muted-foreground">
        Only users without runs or reviews can be deleted. Deactivate the others to keep the audit trail intact.
      </p>
      {remove.error && <Alert>{errorMessage(remove.error, "Couldn't delete the user.")}</Alert>}
      {confirming ? (
        <div className="flex flex-wrap gap-3">
          <Button type="button" size="sm" variant="destructive" onClick={onDelete} disabled={remove.isPending}>
            {remove.isPending ? <LoaderCircle className="animate-spin" aria-hidden /> : <Trash2 aria-hidden />}
            Yes, delete {user.full_name}
          </Button>
          <Button type="button" size="sm" variant="outline" onClick={() => setConfirming(false)}>
            Cancel
          </Button>
        </div>
      ) : (
        <Button type="button" size="sm" variant="outline" onClick={() => setConfirming(true)}>
          <Trash2 aria-hidden />
          Delete user
        </Button>
      )}
    </Section>
  )
}

interface UserEditorProps extends EditorProps {
  onDeleted: () => void
}

export function UserEditor({ user, isSelf, onDeleted }: UserEditorProps) {
  return (
    <Panel
      title={
        <span className="flex flex-col">
          {user.full_name}
          <span className="text-sm font-normal text-muted-foreground">{user.email}</span>
        </span>
      }
      action={
        <span className="text-xs text-muted-foreground">
          Last sign-in: {user.last_login_at ? formatDateTime(user.last_login_at) : "never"}
        </span>
      }
    >
      <div className="space-y-5">
        {user.is_locked && (
          <Alert>This account is locked after too many failed sign-ins. Setting a new password unlocks it.</Alert>
        )}
        <ProfileSection user={user} isSelf={isSelf} />
        <AccessSection user={user} />
        <PasswordSection user={user} />
        {!isSelf && <DeleteSection user={user} onDeleted={onDeleted} />}
      </div>
    </Panel>
  )
}
