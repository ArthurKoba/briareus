window.__MCP_MANAGEMENT_UI_CONFIG__ = {
  preview: "${MANAGEMENT_UI_PREVIEW}".toLowerCase() === "true",
  telemetry: {
    enabled: "${MANAGEMENT_UI_TELEMETRY_ENABLED}".toLowerCase() === "true",
    endpoint: "${MANAGEMENT_UI_TELEMETRY_ENDPOINT}",
    sampleRate: Number("${MANAGEMENT_UI_TELEMETRY_SAMPLE_RATE}") || 1
  },
  events: {
    mode: "${MANAGEMENT_UI_EVENTS_MODE}",
    url: "${MANAGEMENT_UI_EVENTS_URL}"
  }
}
