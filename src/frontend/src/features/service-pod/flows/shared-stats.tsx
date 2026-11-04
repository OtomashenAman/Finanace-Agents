/** A workflow card's live figures (label, value), with a quiet placeholder while loading. */
export function StatList({ items, loading }: { items: [string, string | number][]; loading: boolean }) {
  if (loading) return <p className="text-xs text-muted-foreground">Loading…</p>
  return (
    <dl className="grid grid-cols-3 gap-2">
      {items.map(([label, value]) => (
        <div key={label}>
          <dt className="text-[11px] text-muted-foreground uppercase">{label}</dt>
          <dd className="font-semibold text-brand-navy tabular-nums">{value}</dd>
        </div>
      ))}
    </dl>
  )
}
