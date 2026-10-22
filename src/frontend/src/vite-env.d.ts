/// <reference types="vite/client" />

interface ImportMetaEnv {
  /** API prefix, default "/api" (same origin; proxied by Vite in dev and nginx in prod) */
  readonly VITE_API_BASE_URL?: string
}

interface ImportMeta {
  readonly env: ImportMetaEnv
}
