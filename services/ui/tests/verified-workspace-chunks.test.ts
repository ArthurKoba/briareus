import {describe,expect,it} from "bun:test"
import {readFileSync} from "node:fs"

describe("server-verified resources remain lazy and fail closed",()=>{
  it("never statically loads command widgets from the anonymous auth controller",()=>{
    const src=readFileSync("src/pages/platform/OidcPanelPage.vue","utf8")
    const protectedModules=[
      ["OidcProjectWorkspace","widgets/platform-context/ui/OidcProjectWorkspace.vue"],
      ["CatalogWorkspace","widgets/catalog/ui/CatalogWorkspace.vue"],
      ["ModuleWorkspacePage","pages/modules/ModuleWorkspacePage.vue"],
      ["DashboardOverview","widgets/dashboard/ui/DashboardOverview.vue"],
      ["PlatformSettingsPage","pages/platform/PlatformSettingsPage.vue"],
    ] as const
    for(const [name,path] of protectedModules){
      expect(src).toContain(`const ${name}=protectedPage(()=>import("@/${path}"))`)
      expect(src).not.toContain(`import ${name} from "@/${path}"`)
    }
    expect(src).toContain('v-if="activeContext&&identity"')
    expect(src).toContain('current.kind==="unavailable"?"unavailable"')
    expect(src).toContain('projectLease.value?.remainingMilliseconds()')
    expect(src).toContain('userLease.value?.remainingMilliseconds()')
    expect(src).toContain('errorComponent:ProtectedSectionLoadError')
    expect(src).toContain('loadingComponent:ProtectedSectionLoadState')
  })
  it("missing verified section scripts cannot become a guest, grant or automatic POST",()=>{
    const src=readFileSync("src/pages/platform/ProtectedSectionLoadState.vue","utf8")
    expect(src).toContain(':role="props.failed?\'alert\':\'status\'"')
    expect(src).toContain('window.location.reload()')
    expect(src).not.toContain('fetch(')
    expect(src).not.toContain('oidc/authorize')
    expect(src).not.toContain('credentials')
  })
})
