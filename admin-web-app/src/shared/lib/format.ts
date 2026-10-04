export function formatDate(value: unknown): string {
  if (typeof value !== "string" || !value) return "—"
  const date = new Date(value)
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString()
}

export function formatBytes(value: unknown): string {
  if (typeof value !== "number" || !Number.isFinite(value)) return "—"
  let size = value
  const units = ["B", "KiB", "MiB", "GiB", "TiB"]
  let index = 0
  while (size >= 1024 && index < units.length - 1) { size /= 1024; index += 1 }
  return `${index === 0 ? Math.round(size) : size.toFixed(1)} ${units[index]}`
}

export function textValue(value: unknown): string {
  if (value === null || value === undefined || value === "") return "—"
  if (typeof value === "object") return JSON.stringify(value)
  return String(value)
}
