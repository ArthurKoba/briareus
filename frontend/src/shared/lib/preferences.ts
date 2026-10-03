import { ref, watch } from "vue"

export type ThemePreference = "dark" | "light" | "system"
export type DensityPreference = "comfortable" | "compact"
export type LocalePreference = "en" | "ru"
const STORAGE_KEY="mcp-management:ui"
const theme=ref<ThemePreference>("system")
const sidebarCollapsed=ref(false)
const density=ref<DensityPreference>("comfortable")
const locale=ref<LocalePreference>("ru")
function readPreferences():void{ try{const raw=localStorage.getItem(STORAGE_KEY);if(!raw)return;const p=JSON.parse(raw) as Partial<{theme:ThemePreference;sidebarCollapsed:boolean;density:DensityPreference;locale:LocalePreference}>;if(["dark","light","system"].includes(String(p.theme)))theme.value=p.theme as ThemePreference;sidebarCollapsed.value=Boolean(p.sidebarCollapsed);if(p.density==="compact"||p.density==="comfortable")density.value=p.density;if(p.locale==="en"||p.locale==="ru")locale.value=p.locale}catch{/* ignore corrupt browser-local preferences */} }
function persist():void{localStorage.setItem(STORAGE_KEY,JSON.stringify({theme:theme.value,sidebarCollapsed:sidebarCollapsed.value,density:density.value,locale:locale.value}))}
function applyTheme():void{const dark=window.matchMedia("(prefers-color-scheme: dark)").matches;document.documentElement.classList.toggle("dark",theme.value==="dark"||(theme.value==="system"&&dark))}
function applyDensity():void{document.documentElement.dataset.density=density.value}
readPreferences();watch([theme,sidebarCollapsed,density,locale],persist);watch(theme,applyTheme,{immediate:true});watch(density,applyDensity,{immediate:true})
export const uiPreferences={theme,sidebarCollapsed,density,locale}
export function useUiPreferences(){return uiPreferences}
