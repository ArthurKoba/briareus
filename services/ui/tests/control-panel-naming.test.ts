import { describe, expect, it } from "bun:test"
import { readFileSync } from "node:fs"

describe("Control Panel canonical product identity", () => {
  it("does not show deprecated Briareus Admin or Management product labels", () => {
    const en = readFileSync("src/shared/i18n/locales/en.ts", "utf8")
    const ru = readFileSync("src/shared/i18n/locales/ru.ts", "utf8")
    for (const text of [en, ru]) {
      expect(text).not.toContain("Authorization/Admin")
      expect(text).not.toContain("Admin API")
      expect(text).not.toContain("Admin UI")
    }
  })

  it("does not advertise retired private UI DNS in own Compose", () => {
    const compose=readFileSync("docker-compose.yaml","utf8")
    expect(compose).toContain('aliases: ["briareus-control-panel-ui"]')
    expect(compose).not.toContain("briareus-admin-ui")
  })

  it("avoids retired terminology in current module copy", () => {
    const catalog=readFileSync("src/features/modules/catalog.ts","utf8")
    expect(catalog).not.toContain("management API")
    expect(catalog).toContain("Control Panel API")
  })

  it("publishes only the canonical private UI DNS in maintained docs", () => {
    const readme = readFileSync("README.md", "utf8")
    expect(readme).toContain("briareus-control-panel-ui:8080")
    expect(readme).not.toContain("briareus-admin-ui")
  })

  it("keeps owner-required directory-wide External Services Coolify Watch",()=>{
    const compose=readFileSync("docker-compose.coolify.yaml","utf8")
    expect(compose).toContain('"services/ui/**"')
    expect(compose).toContain('"services/external/**"')
    expect(compose).not.toContain('services/external/docker-compose.coolify.yaml')
  })

  it("uses own native Control Panel login without provider-hosted navigation",()=>{
    const login=readFileSync("src/pages/platform/ControlPanelAccessPage.vue","utf8")
    const native=login.indexOf('prepareNativeRauthyLogin')
    const embedded=login.indexOf('<form class="space-y-4"')
    expect(native).toBeGreaterThan(0)
    expect(embedded).toBeGreaterThan(native)
    const identity=readFileSync("src/features/platform/ui/RauthySignIn.vue","utf8")
    expect(identity).not.toContain('href="/api/v1/auth/authorize"')
    expect(identity).not.toContain('redirecting')
    expect(login).not.toContain("oauthExpanded")
    expect(login).not.toContain("readRauthyPanelState(")
    expect(login).toContain(':disabled="true"')
    expect(login).not.toContain('v-model="password"')
    expect(login).not.toContain('v-model="username"')
    expect(login).not.toContain('autocomplete="current-password"')
    expect(login).toContain("native==='prepared'")
  })

  it("uses one authoritative provider snapshot and discards it on logout or expiry",()=>{
    const parent=readFileSync("src/pages/platform/OidcPanelPage.vue","utf8")
    const login=readFileSync("src/pages/platform/ControlPanelAccessPage.vue","utf8")
    const child=readFileSync("src/features/platform/ui/RauthySignIn.vue","utf8")
    expect(parent).toContain("providerSnapshot.value=session")
    expect(parent).toContain('providerSnapshot.value={kind:"signed_out"}')
    expect(parent).toContain('providerSnapshot.value={kind:"unavailable",reason:"session_unavailable"}')
    expect(parent).toContain('@provider-state="onLoginProviderState"')
    expect(login).toContain('<RauthySignIn :initial-state="initialSession"')
    expect(child).toContain("if(props.initialState)")
    expect(child).toContain("if(!props.initialState)")
    expect(child).toContain("if(props.initialState||busy.value)return")
    expect(child).toContain('if(props.managedLogout){emit("logoutRequested");return}')
    expect(login).toContain(':managed-logout="managedLogout"')
    expect(parent).toContain('@logout-requested="logout"')
  })

  it("retains original public paths and a single UI Vite base", () => {
    const vite = readFileSync("vite.config.ts", "utf8")
    expect(vite).toContain('base:"/panel/"')
    expect(vite).not.toContain("briareus-admin-ui")
  })
})
