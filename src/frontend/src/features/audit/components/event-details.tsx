import type { AuditEvent } from "../api"

function value(v: unknown): string {
  if (v === null || v === undefined) return "—"
  if (typeof v === "object") return JSON.stringify(v)
  return String(v)
}

/** Everything recorded for one event (secrets are never recorded). */
export function EventDetails({ event }: { event: AuditEvent }) {
  const facts: [string, string][] = [
    ["Event", event.event_type],
    ["Time (UTC)", new Date(event.created_at).toISOString().replace("T", " ").slice(0, 19)],
    ["Actor", event.actor ? `${event.actor.full_name} <${event.actor.email}>` : "Anonymous or deleted user"],
  ]
  if (event.subject_user) facts.push(["About", `${event.subject_user.full_name} <${event.subject_user.email}>`])
  if (event.ip) facts.push(["IP address", event.ip])
  if (event.user_agent) facts.push(["Browser", event.user_agent])
  const details = Object.entries(event.details)

  return (
    <div className="grid gap-4 rounded-md bg-secondary/40 p-4 text-sm sm:grid-cols-2">
      <dl className="space-y-1.5">
        {facts.map(([k, v]) => (
          <div key={k} className="grid grid-cols-[110px_minmax(0,1fr)] gap-2">
            <dt className="text-muted-foreground">{k}</dt>
            <dd className="break-all">{v}</dd>
          </div>
        ))}
      </dl>
      <dl className="space-y-1.5">
        {details.length === 0 && <p className="text-muted-foreground">No further details.</p>}
        {details.map(([k, v]) => (
          <div key={k} className="grid grid-cols-[110px_minmax(0,1fr)] gap-2">
            <dt className="text-muted-foreground">{k.replace(/_/g, " ")}</dt>
            <dd className="font-mono text-xs break-all">{value(v)}</dd>
          </div>
        ))}
      </dl>
    </div>
  )
}
