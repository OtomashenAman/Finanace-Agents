/** A case's invoice rows as the workflows keep them in its state */
export interface InvoiceState {
  id: string
  number: string
  due_date: string
  balance: string
  days_overdue?: number
}

export const money = (value: unknown, currency: unknown) =>
  `${String(currency ?? "")} ${Number(value ?? 0).toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`

export const fmt = (value: string | number, currency?: string | null) =>
  `${currency ?? ""} ${Number(value).toLocaleString(undefined, { maximumFractionDigits: 0 })}`.trim()
