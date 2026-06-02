/// <reference types="vite/client" />

interface ImportMetaEnv {
  readonly VITE_USE_MOCK:          string
  readonly VITE_API_URL:           string
  readonly VITE_COGNITO_DOMAIN:    string
  readonly VITE_COGNITO_CLIENT_ID: string
  readonly VITE_APP_URL:           string
}

interface ImportMeta {
  readonly env: ImportMetaEnv
}
