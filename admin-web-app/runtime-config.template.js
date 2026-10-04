window.__KOBA_ADMIN_UI_CONFIG__ = {
  preview: "${ADMIN_UI_PREVIEW}".toLowerCase() === "true",
  apiBaseUrl: "${ADMIN_API_BASE_URL}",
  telemetry: {
    enabled: "${ADMIN_UI_TELEMETRY_ENABLED}".toLowerCase() === "true",
    sampleRate: Number("${ADMIN_UI_TELEMETRY_SAMPLE_RATE}") || 1
  },
  events: {
    mode: "${ADMIN_UI_EVENTS_MODE}"
  }
}
