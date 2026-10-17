/// <reference types="vite/client" />

interface ImportMetaEnv {
  /** "false" to call the real FastAPI backend instead of the in-browser mock */
  readonly VITE_USE_MOCK?: string
  /** Backend base URL (default: /api, proxied by Vite in dev) */
  readonly VITE_API_URL?: string
  /** MapLibre style JSON URL */
  readonly VITE_MAP_STYLE_URL?: string
}

interface ImportMeta {
  readonly env: ImportMetaEnv
}
