import { moduleById, type ModuleId, type ModuleView } from "@/features/modules/catalog"

/** Public, noncredential URL state. Hash fragments NEVER contain module configuration values. */
export interface ModuleLocation {
  module: ModuleId
  view: ModuleView
}

const views: readonly ModuleView[] = ["overview", "settings", "global"]

export function parseModuleLocation(hash: string, fallback: ModuleId = "web"): ModuleLocation {
  const [root, page, moduleId, panel, extra] = hash.replace(/^#/, "").split("/")
  if (root !== "platform" || page !== "mcp" || extra !== undefined) {
    return { module: fallback, view: "overview" }
  }
  const module = moduleId && moduleById(moduleId) ? moduleId as ModuleId : fallback
  const view = panel && views.includes(panel as ModuleView) ? panel as ModuleView : "overview"
  return { module, view }
}

export function moduleLocationHash(id: ModuleId, view: ModuleView): string {
  return `#platform/mcp/${id}/${view}`
}
