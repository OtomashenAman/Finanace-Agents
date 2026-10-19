/** Format a decimal string like "-11500.5" as "-11,500.50" without going through floats. */
export function formatMoney(value: string | number | null | undefined): string {
  if (value === null || value === undefined || value === "") return "—"
  const text = String(value).trim()
  const match = /^(-?)(\d+)(?:\.(\d+))?$/.exec(text)
  if (!match) return text
  const [, sign, whole, fraction = ""] = match
  const grouped = whole.replace(/\B(?=(\d{3})+(?!\d))/g, ",")
  return `${sign}${grouped}.${fraction.padEnd(2, "0").slice(0, 2)}`
}

/** "12,500.00" or "12500" typed by a user -> "12500.00"-style decimal string for the API. */
export function parseMoneyInput(value: string): string {
  return value.replace(/[,\s$]/g, "")
}

export function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`
}

export function formatDateTime(iso: string | null): string {
  if (!iso) return "—"
  return new Intl.DateTimeFormat(undefined, { dateStyle: "medium", timeStyle: "short" }).format(new Date(iso))
}
