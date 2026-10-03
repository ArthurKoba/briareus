import { fileURLToPath, URL } from "node:url"

import tailwindcss from "@tailwindcss/vite"
import vue from "@vitejs/plugin-vue"
import { defineConfig, loadEnv } from "vite"

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), "")
  const backend = env.VITE_MANAGEMENT_DEV_BACKEND || "http://localhost:8000"

  return {
    base: "/admin/",
    plugins: [vue(), tailwindcss()],
    resolve: {
      alias: { "@": fileURLToPath(new URL("./src", import.meta.url)) },
    },
    server: {
      proxy: {
        "/api": {
          target: backend,
          changeOrigin: true,
          rewrite: (path) => path.replace(/^\/api/, "/admin/api"),
        },
      },
    },
  }
})
