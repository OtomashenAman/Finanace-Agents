import { useState } from "react"
import { useForm, useWatch } from "react-hook-form"
import { zodResolver } from "@hookform/resolvers/zod"
import { LoaderCircle } from "lucide-react"
import { toast } from "sonner"

import { Alert } from "@/components/ui/alert"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Panel } from "@/features/agent-catalog/workspace/components/panel"
import { errorMessage } from "@/lib/api"

import type { PodWorkflow, UserRole } from "@/features/auth/api"
import { defaultAreas, ROLE_WORKFLOWS } from "@/features/auth/roles"

import type { Assignment, ManagedUser } from "../api"
import { describedBy, roleHint } from "../form-utils"
import { useCreateUser } from "../hooks"
import { createUserSchema, PASSWORD_MIN_LENGTH, type CreateUserValues } from "../schema"
// Agent Catalog and Finance POD are hidden for now: areas follow the role, no agent assignments
// import { AreasEditor } from "./areas-editor"
// import { AssignmentsEditor } from "./assignments-editor"
import { EntitiesEditor } from "./entities-editor"
import { Field, RoleSelect } from "./form-bits"
import { WorkflowsEditor } from "./workflows-editor"

interface CreateUserFormProps {
  onCreated: (user: ManagedUser) => void
  onCancel: () => void
}

export function CreateUserForm({ onCreated, onCancel }: CreateUserFormProps) {
  const create = useCreateUser()
  const [assignments] = useState<Assignment[]>([])
  const [entityIds, setEntityIds] = useState<string[]>([])
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
  // Everything the chosen role allows (the areas editor is hidden for now)
  const areas = defaultAreas(role)
  // The role's workflows until the admin changes them; picking another role starts over
  const [picked, setPicked] = useState<{ role: UserRole; value: PodWorkflow[] } | null>(null)
  const podWorkflows = picked?.role === role ? picked.value : ROLE_WORKFLOWS[role]

  const onSubmit = handleSubmit((values) =>
    create.mutate(
      // Admins get every agent and entity anyway; don't store assignments for them
      {
        ...values,
        areas,
        pod_workflows: values.role === "finance_admin" ? [] : podWorkflows,
        assignments: values.role === "finance_admin" ? [] : assignments,
        entity_ids: values.role === "finance_admin" ? [] : entityIds,
      },
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

        {/* Hidden for now with the Agent Catalog and Finance POD:
        <div className="space-y-2">
          <h3 className="text-sm font-semibold text-brand-navy">Areas</h3>
          <AreasEditor role={role} value={areas} onChange={setAreas} disabled={create.isPending} />
        </div>

        {role !== "finance_admin" && (
          <div className="space-y-2">
            <h3 className="text-sm font-semibold text-brand-navy">Agent access</h3>
            <AssignmentsEditor value={assignments} onChange={setAssignments} disabled={create.isPending} />
          </div>
        )}
        */}

        <div className="space-y-2">
          <h3 className="text-sm font-semibold text-brand-navy">Service POD workflows</h3>
          <WorkflowsEditor
            role={role}
            value={podWorkflows}
            onChange={(value) => setPicked({ role, value })}
            disabled={create.isPending}
          />
        </div>
        {role !== "finance_admin" && (
          <div className="space-y-2">
            <h3 className="text-sm font-semibold text-brand-navy">Legal entities</h3>
            <EntitiesEditor value={entityIds} onChange={setEntityIds} disabled={create.isPending} />
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
