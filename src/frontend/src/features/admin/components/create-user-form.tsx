import { useState } from "react"
import { useForm, useWatch } from "react-hook-form"
import { zodResolver } from "@hookform/resolvers/zod"
import { LoaderCircle } from "lucide-react"
import { toast } from "sonner"

import { Alert } from "@/components/ui/alert"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Panel } from "@/features/agent-catalog/workspace/components/panel"

import type { Assignment, ManagedUser } from "../api"
import { describedBy, errorMessage, roleHint } from "../form-utils"
import { useCreateUser } from "../hooks"
import { createUserSchema, PASSWORD_MIN_LENGTH, type CreateUserValues } from "../schema"
import { AssignmentsEditor } from "./assignments-editor"
import { Field, RoleSelect } from "./form-bits"

interface CreateUserFormProps {
  onCreated: (user: ManagedUser) => void
  onCancel: () => void
}

export function CreateUserForm({ onCreated, onCancel }: CreateUserFormProps) {
  const create = useCreateUser()
  const [assignments, setAssignments] = useState<Assignment[]>([])
  const {
    register,
    handleSubmit,
    control,
    formState: { errors },
  } = useForm<CreateUserValues>({
    resolver: zodResolver(createUserSchema),
    defaultValues: { full_name: "", email: "", role: "user", password: "" },
    mode: "onTouched",
  })
  const role = useWatch({ control, name: "role" })

  const onSubmit = handleSubmit((values) =>
    create.mutate(
      // Admins get every agent anyway; don't store assignments for them
      { ...values, assignments: values.role === "user" ? assignments : [] },
      {
        onSuccess: (user) => {
          toast.success(`${user.full_name} created`)
          onCreated(user)
        },
      },
    ),
  )

  return (
    <Panel title="New user">
      <form onSubmit={onSubmit} noValidate className="space-y-5" aria-label="New user">
        {create.error && <Alert>{errorMessage(create.error, "Couldn't create the user.")}</Alert>}

        <div className="grid gap-5 sm:grid-cols-2">
          <Field id="new-name" label="Full name" error={errors.full_name?.message}>
            <Input id="new-name" autoFocus {...describedBy("new-name", errors.full_name?.message)} {...register("full_name")} />
          </Field>
          <Field id="new-email" label="Work email" error={errors.email?.message}>
            <Input
              id="new-email"
              type="email"
              inputMode="email"
              autoComplete="off"
              placeholder="name@company.com"
              {...describedBy("new-email", errors.email?.message)}
              {...register("email")}
            />
          </Field>
          <Field id="new-role" label="Role" hint={roleHint(role)}>
            <RoleSelect id="new-role" {...register("role")} />
          </Field>
          <Field
            id="new-password"
            label="Initial password"
            error={errors.password?.message}
            hint={`At least ${PASSWORD_MIN_LENGTH} characters. Share it with the user securely.`}
          >
            <Input
              id="new-password"
              type="password"
              autoComplete="new-password"
              {...describedBy("new-password", errors.password?.message)}
              {...register("password")}
            />
          </Field>
        </div>

        {role === "user" && (
          <div className="space-y-2">
            <h3 className="text-sm font-semibold text-brand-navy">Agent access</h3>
            <AssignmentsEditor value={assignments} onChange={setAssignments} disabled={create.isPending} />
          </div>
        )}

        <div className="flex flex-wrap gap-3 border-t pt-5">
          <Button type="submit" disabled={create.isPending}>
            {create.isPending && <LoaderCircle className="animate-spin" aria-hidden />}
            Create user
          </Button>
          <Button type="button" variant="outline" onClick={onCancel} disabled={create.isPending}>
            Cancel
          </Button>
        </div>
      </form>
    </Panel>
  )
}
