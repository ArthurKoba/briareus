import { fileURLToPath, URL } from "node:url"

import tailwindcss from "@tailwindcss/vite"
import vue from "@vitejs/plugin-vue"
import { defineConfig } from "vite"

export default defineConfig({
  base: "/admin/",
  plugins: [vue(), tailwindcss()],
  resolve: {
    alias: { "@": fileURLToPath(new URL("./src", import.meta.url)) },
  },
  server: {
    proxy: { "/admin/api": "http://localhost:8000" },
  },
})
