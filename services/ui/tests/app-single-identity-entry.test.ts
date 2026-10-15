import {describe,expect,it} from "bun:test"
import {readFileSync} from "node:fs"

describe("one Control Panel authentication root",()=>{
  it("does not branch into the legacy PlatformPort or guest Identity views",()=>{
    const entry=readFileSync("src/app/App.vue","utf8")
    expect(entry).toContain('import("@/pages/platform/OidcPanelPage.vue").catch(()=>ControlPanelChunkFailure)')
    expect(entry).toContain("<Suspense v-else>")
    expect(entry).toContain("<OidcPanelPage/>")
    expect(entry).toContain('t("app.loading")')
    const failure=readFileSync("src/app/ControlPanelChunkFailure.vue","utf8")
    expect(failure).toContain('t("app.loadFailed")')
    expect(failure).toContain('window.location.reload()')
    expect(failure).not.toContain("platformPort")
    expect(entry).toContain('import.meta.env.DEV')
    for(const retired of [
      "platformPort", "projectContext", "installServerProjection", "restoreBffOwnerBoundary",
      "ControlPanelShell", "ControlPanelAccessPage", "PlatformHomePage", "AuthSessionExpired",
      "temporary-first-user", "PublicIdentityStatus", "oauthExpanded",
    ])expect(entry).not.toContain(retired)
  })
})
