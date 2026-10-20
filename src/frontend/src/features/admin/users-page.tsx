import { useDeferredValue, useState } from "react"
import { Inbox, LoaderCircle, Plus, Search } from "lucide-react"

import { AppPage } from "@/components/layout/app-page"
import { Alert } from "@/components/ui/alert"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { useCurrentUser } from "@/features/auth/hooks"
import { ROLE_LABELS } from "@/features/auth/roles"
import { cn } from "@/lib/utils"

import type { ManagedUser } from "./api"
import { AdminTabs } from "./components/admin-tabs"
import { CreateUserForm } from "./components/create-user-form"
import { UserEditor } from "./components/user-editor"
import { useUsers } from "./hooks"

function StatusPill({ user }: { user: ManagedUser }) {
  const [label, tone] = !user.is_active
    ? ["Inactive", "bg-muted text-muted-foreground"]
    : user.is_locked
      ? ["Locked", "bg-destructive/10 text-destructive"]
      : ["Active", "bg-emerald-50 text-emerald-700"]
  return <span className={cn("rounded px-2 py-0.5 text-xs font-medium", tone)}>{label}</span>
}

function access(user: ManagedUser): string {
  if (user.role === "finance_admin") return "All agents"
  const agents = new Set(user.assignments.map((a) => a.agent_name))
  return agents.size ? [...agents].join(", ") : "No agents"
}

interface UsersTableProps {
  users: ManagedUser[]
  selectedId: string | null
  onSelect: (id: string) => void
}

function UsersTable({ users, selectedId, onSelect }: UsersTableProps) {
  return (
    <div className="overflow-x-auto">
      <table className="w-full min-w-[560px] text-sm">
        <thead>
          <tr className="border-b text-left text-xs tracking-wide text-muted-foreground uppercase">
            <th className="py-2 pr-4 font-semibold">User</th>
            <th className="py-2 pr-4 font-semibold">Role</th>
            <th className="py-2 pr-4 font-semibold">Access</th>
            <th className="py-2 font-semibold">Status</th>
          </tr>
        </thead>
        <tbody className="divide-y">
          {users.map((user) => (
            <tr
              key={user.id}
              className={cn("cursor-pointer hover:bg-secondary/40", user.id === selectedId && "bg-secondary/60")}
              onClick={() => onSelect(user.id)}
            >
              <td className="py-3 pr-4">
                <button
                  type="button"
                  className="text-left font-semibold text-primary hover:underline"
                  onClick={(e) => {
                    e.stopPropagation()
                    onSelect(user.id)
                  }}
                  aria-current={user.id === selectedId ? "true" : undefined}
                >
                  {user.full_name}
                </button>
                <p className="text-xs text-muted-foreground">{user.email}</p>
              </td>
              <td className="py-3 pr-4">{ROLE_LABELS[user.role]}</td>
              <td className="max-w-[220px] truncate py-3 pr-4 text-muted-foreground" title={access(user)}>
                {access(user)}
              </td>
              <td className="py-3">
                <StatusPill user={user} />
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

type Selection = { kind: "none" } | { kind: "new" } | { kind: "user"; id: string }

export function UsersPage() {
  const { data: me } = useCurrentUser()
  const [search, setSearch] = useState("")
  const query = useDeferredValue(search.trim())
  const { data: users, isPending, isError } = useUsers(query)
  const [selection, setSelection] = useState<Selection>({ kind: "none" })

  const selected = selection.kind === "user" ? users?.find((u) => u.id === selection.id) : undefined

  return (
    <AppPage
      title="Admin Settings · Users"
      subtitle="Create accounts, choose who prepares and approves each agent, reset passwords and deactivate access."
    >
      <AdminTabs />
      <div className="grid items-start gap-6 xl:grid-cols-[minmax(0,1fr)_minmax(0,1.1fr)]">
        <section className="rounded-lg border bg-card p-5 sm:p-6" aria-labelledby="users-title">
          <div className="flex flex-wrap items-center justify-between gap-3 border-b pb-4">
            <h2 id="users-title" className="text-lg font-semibold text-brand-navy">
              Users
            </h2>
            <Button type="button" size="sm" onClick={() => setSelection({ kind: "new" })}>
              <Plus aria-hidden />
              New user
            </Button>
          </div>

          <div className="relative mt-4">
            <Search className="absolute top-1/2 left-3 size-4 -translate-y-1/2 text-muted-foreground" aria-hidden />
            <Input
              type="search"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              placeholder="Search by name or email"
              aria-label="Search users"
              className="pl-9"
            />
          </div>

          <div className="pt-4">
            {isPending && (
              <div className="flex justify-center py-10" role="status">
                <LoaderCircle className="size-6 animate-spin text-primary" aria-hidden />
                <span className="sr-only">Loading users…</span>
              </div>
            )}
            {isError && <Alert>Couldn't load users. Refresh the page to try again.</Alert>}
            {users?.length === 0 && (
              <div className="flex flex-col items-center gap-2 py-10 text-center">
                <Inbox className="size-7 text-muted-foreground" aria-hidden />
                <p className="font-medium">No users found</p>
              </div>
            )}
            {users && users.length > 0 && (
              <UsersTable
                users={users}
                selectedId={selected?.id ?? null}
                onSelect={(id) => setSelection({ kind: "user", id })}
              />
            )}
          </div>
        </section>

        {selection.kind === "new" && (
          <CreateUserForm
            onCreated={(user) => setSelection({ kind: "user", id: user.id })}
            onCancel={() => setSelection({ kind: "none" })}
          />
        )}
        {selected && (
          <UserEditor
            key={selected.id}
            user={selected}
            isSelf={selected.id === me?.id}
            onDeleted={() => setSelection({ kind: "none" })}
          />
        )}
        {selection.kind === "none" && (
          <div className="hidden rounded-lg border border-dashed bg-card px-6 py-16 text-center text-sm text-muted-foreground xl:block">
            Select a user to edit their profile, agent access or password.
          </div>
        )}
      </div>
    </AppPage>
  )
}
