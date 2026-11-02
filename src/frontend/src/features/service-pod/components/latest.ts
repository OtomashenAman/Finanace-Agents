/** Newest-first snapshots (or rows that carry one) split into the latest per company and
 *  entity, and the older ones of each (shown on request). */
export function splitLatest<T>(items: T[], key: (item: T) => string): { latest: T[]; older: Map<string, T[]> } {
  const latest: T[] = []
  const older = new Map<string, T[]>()
  for (const item of items) {
    const k = key(item)
    if (older.has(k)) older.get(k)!.push(item)
    else {
      latest.push(item)
      older.set(k, [])
    }
  }
  return { latest, older }
}

export function snapshotKey<T extends { company_name: string; entity: { code: string } }>(s: T): string {
  return `${s.company_name}|${s.entity.code}`
}
