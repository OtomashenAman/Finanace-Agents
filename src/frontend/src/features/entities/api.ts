import { apiRequest } from "@/lib/api"

export interface LegalEntity {
  id: string
  code: string
  name: string
  is_active: boolean
}

/** How runs and users show their entity */
export interface EntityRef {
  id: string
  code: string
  name: string
}

export const entitiesApi = {
  /** Finance Admin: every entity. User: the entities they work for. */
  list: () => apiRequest<LegalEntity[]>("/entities"),
  create: (body: { code: string; name: string }) =>
    apiRequest<LegalEntity>("/entities", { method: "POST", json: body }),
  update: ({ id, ...body }: { id: string; name?: string; is_active?: boolean }) =>
    apiRequest<LegalEntity>(`/entities/${encodeURIComponent(id)}`, { method: "PATCH", json: body }),
}

export function entityLabel(entity: EntityRef): string {
  return `${entity.code} · ${entity.name}`
}
