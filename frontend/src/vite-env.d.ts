/// <reference types="vite/client" />

interface ImportMetaEnv {
  /** "mock" | "hybrid" (default) | "real" — which API implementation the app uses */
  readonly VITE_API_MODE?: string
  /** Legacy: "true" is equivalent to VITE_API_MODE=mock */
  readonly VITE_USE_MOCK?: string
  /** API base URL (default: /api/v1, proxied by Vite in dev) */
  readonly VITE_API_URL?: string
  /** MapLibre style JSON URL */
  readonly VITE_MAP_STYLE_URL?: string
}

interface ImportMeta {
  readonly env: ImportMetaEnv
}
