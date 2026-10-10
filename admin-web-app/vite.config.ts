import { fileURLToPath, URL } from "node:url"
import { readFileSync } from "node:fs"

import tailwindcss from "@tailwindcss/vite"
import vue from "@vitejs/plugin-vue"
import { defineConfig } from "vite"

/** Immutable UI SOURCE PACKAGE version, not guessed deployment or server
 * identity. No Git credentials, Team OTLP secrets, container TZ or ENV. */
const manifest=JSON.parse(readFileSync(fileURLToPath(new URL("./package.json",import.meta.url)),"utf8")) as {version:string}
if(!/^\d+\.\d+\.\d+(?:[-+][0-9A-Za-z.-]+)?$/.test(manifest.version)){
  throw new Error("Invalid Briareus package version")
}
/** No implicit proxy to an old Admin API or guessed backend port. */
export default defineConfig({
  define:{__BRIAREUS_UI_PACKAGE_VERSION__:JSON.stringify(manifest.version)},
  base:"/",
  plugins:[vue(),tailwindcss()],
  resolve:{alias:{"@":fileURLToPath(new URL("./src",import.meta.url))}},
  server:{host:"127.0.0.1"},
  preview:{host:"127.0.0.1"},
})
