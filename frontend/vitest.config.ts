import vue from "@vitejs/plugin-vue"
import { defineConfig } from "vitest/config"

export default defineConfig({
  plugins: [vue()],
  resolve: {
    alias: { "@": new URL("./src", import.meta.url).pathname },
  },
  test: {
    environment: "happy-dom",
    include: ["tests/**/*.test.ts"],
    maxWorkers: 1,
    restoreMocks: true,
    clearMocks: true,
  },
})
