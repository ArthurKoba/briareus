/// <reference types="vite/client" />

declare module "*.vue" {
  import type { DefineComponent } from "vue"

  const component: DefineComponent<Record<string, never>, Record<string, never>, unknown>
  export default component
}

/** Compile-time source package version from reviewed package.json, not ENV. */
declare const __BRIAREUS_UI_PACKAGE_VERSION__: string
