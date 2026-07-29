/// <reference types="vite/client" />

interface ImportMetaEnv {
  /** Absolute API base for split-origin hosting. Empty means same-origin. */
  readonly VITE_API_BASE_URL?: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}
