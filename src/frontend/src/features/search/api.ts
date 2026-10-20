import { apiRequest } from "@/lib/api"

export type HitKind = "run" | "agent" | "user" | "entity"

export interface SearchHit {
  kind: HitKind
  title: string
  subtitle: string | null
  link: string
}

export interface SearchResults {
  query: string
  hits: SearchHit[]
}

export const searchApi = {
  search: (q: string) => apiRequest<SearchResults>(`/search?q=${encodeURIComponent(q)}`),
}
