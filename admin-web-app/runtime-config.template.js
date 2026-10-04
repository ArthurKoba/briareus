window.__MCP_ADMIN_UI_CONFIG__ = {
  preview: "${ADMIN_UI_PREVIEW}".toLowerCase() === "true",
  telemetry: {
    enabled: "${ADMIN_UI_TELEMETRY_ENABLED}".toLowerCase() === "true",
    endpoint: "${ADMIN_UI_TELEMETRY_ENDPOINT}",
    sampleRate: Number("${ADMIN_UI_TELEMETRY_SAMPLE_RATE}") || 1
  },
  events: {
    mode: "${ADMIN_UI_EVENTS_MODE}",
    url: "${ADMIN_UI_EVENTS_URL}"
  }
}
