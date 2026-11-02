import type { ReactNode } from "react"

/** A step's recorded result, readable: lists of rows become small tables, nested objects
 *  definition lists, ids and amounts stay as recorded. */
function label(key: string): string {
  return key.replace(/_id$/, "").replace(/_/g, " ").replace(/^\w/, (c) => c.toUpperCase())
}

function scalar(value: unknown): ReactNode {
  if (value === null || value === undefined || value === "") return <span className="text-muted-foreground">—</span>
  if (typeof value === "boolean") return value ? "Yes" : "No"
  if (typeof value === "string" && /^\d{4}-\d{2}-\d{2}T/.test(value)) return new Date(value).toLocaleString()
  return String(value)
}

function isRow(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value)
}

function Table({ rows }: { rows: Record<string, unknown>[] }) {
  const columns = Array.from(new Set(rows.flatMap((r) => Object.keys(r)))).filter((k) =>
    rows.some((r) => !isRow(r[k]) && !Array.isArray(r[k])),
  )
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-xs">
        <thead className="text-left text-muted-foreground">
          <tr>
            {columns.map((c) => (
              <th key={c} className="py-1 pr-3 font-medium">
                {label(c)}
              </th>
            ))}
          </tr>
        </thead>
        <tbody className="divide-y divide-border/60">
          {rows.map((r, i) => (
            <tr key={i}>
              {columns.map((c) => (
                <td key={c} className="py-1 pr-3 align-top">
                  {scalar(r[c])}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

export function ResultView({ value }: { value: Record<string, unknown> }) {
  const entries = Object.entries(value).filter(([, v]) => !(Array.isArray(v) && v.length === 0))
  if (entries.length === 0) return null
  return (
    <dl className="mt-1 space-y-1 text-xs">
      {entries.map(([key, v]) => (
        <div key={key} className={Array.isArray(v) && v.some(isRow) ? "space-y-1" : "flex flex-wrap gap-x-2"}>
          <dt className="font-medium text-muted-foreground">{label(key)}:</dt>
          <dd className="min-w-0 text-foreground/90">
            {Array.isArray(v) ? (
              v.every(isRow) ? (
                <Table rows={v} />
              ) : (
                v.map(String).join(", ")
              )
            ) : isRow(v) ? (
              Object.keys(v).length > 0 && Object.values(v).every((x) => !isRow(x) && !Array.isArray(x)) ? (
                Object.entries(v)
                  .map(([k, x]) => `${label(k)} ${x === null ? "—" : String(x)}`)
                  .join(" · ")
              ) : (
                <div className="border-l-2 border-border/70 pl-2">
                  <ResultView value={v} />
                </div>
              )
            ) : (
              scalar(v)
            )}
          </dd>
        </div>
      ))}
    </dl>
  )
}
