import { fileURLToPath, URL } from "node:url"

import tailwindcss from "@tailwindcss/vite"
import vue from "@vitejs/plugin-vue"
import { defineConfig } from "vite"

/** No implicit proxy to an old Admin API or guessed backend port. */
export default defineConfig({
  base:"/",
  plugins:[vue(),tailwindcss()],
  resolve:{alias:{"@":fileURLToPath(new URL("./src",import.meta.url))}},
  server:{host:"127.0.0.1"},
  preview:{host:"127.0.0.1"},
})
