<script setup lang="ts">
import { useI18n } from "vue-i18n"
import { setLocale } from "@/shared/i18n"
import { uiPreferences } from "@/shared/lib/preferences"
import { browserTelemetry } from "@/features/platform/model/browser-telemetry"
import { platformCutoverReadiness } from "@/features/platform/api/cutover-contract"
import { projectContext } from "@/features/platform/model/project-context"
import OwnerReadinessPanel from "@/features/platform/ui/OwnerReadinessPanel.vue"
import PageHeader from "@/shared/ui/PageHeader.vue"
import { Button } from "@/shared/ui/button"
import { Card, CardContent, CardHeader, CardTitle } from "@/shared/ui/card"
import {
  Select, SelectTrigger, SelectValue, SelectContent, SelectItem,
} from "@/shared/ui/select"
import { Switch } from "@/shared/ui/switch"

const {t}=useI18n()
const uiPackageVersion=__BRIAREUS_UI_PACKAGE_VERSION__
function localeChanged(value:unknown):void {
  if(value==="en"||value==="ru")setLocale(value)
}
function themeChanged(value:unknown):void {
  if(value==="dark"||value==="light"||value==="system")uiPreferences.theme.value=value
}
function densityChanged(value:unknown):void {
  if(value==="compact"||value==="comfortable")uiPreferences.density.value=value
}
function zoneChanged(value:unknown):void {
  if(value==="UTC"||value==="system")uiPreferences.displayTimeZone.value=value
}
</script>
<template>
  <div class="space-y-6">
    <PageHeader :title="t('platform.navigation.settings')" :description="t('platform.settingsHint')" />
    <Card>
      <CardHeader><CardTitle class="text-base">{{t('settings.interface')}}</CardTitle></CardHeader>
      <CardContent class="space-y-5">
        <div class="max-w-sm space-y-2 text-sm">
          <p class="font-semibold">{{t('settings.language')}}</p>
          <Select :model-value="uiPreferences.locale.value" @update:model-value="localeChanged">
            <SelectTrigger class="min-h-10" :aria-label="t('settings.language')"><SelectValue/></SelectTrigger>
            <SelectContent>
              <SelectItem value="ru">Русский</SelectItem>
              <SelectItem value="en">English</SelectItem>
            </SelectContent>
          </Select>
        </div>
        <div class="max-w-sm space-y-2 text-sm">
          <p class="font-semibold">{{t('settings.theme')}}</p>
          <Select :model-value="uiPreferences.theme.value" @update:model-value="themeChanged">
            <SelectTrigger class="min-h-10" :aria-label="t('settings.theme')"><SelectValue/></SelectTrigger>
            <SelectContent>
              <SelectItem value="system">{{t('common.system')}}</SelectItem>
              <SelectItem value="light">{{t('common.light')}}</SelectItem>
              <SelectItem value="dark">{{t('common.dark')}}</SelectItem>
            </SelectContent>
          </Select>
        </div>
        <fieldset class="space-y-3">
          <legend class="text-sm font-semibold">{{uiPreferences.locale.value==='ru'?'Цветовой акцент':'Accent color'}}</legend>
          <div class="flex flex-wrap gap-2">
            <Button v-for="preset in (['graphite','indigo','amber'] as const)" :key="preset" type="button" size="sm"
              :variant="uiPreferences.accent.value===preset?'default':'outline'"
              :aria-pressed="uiPreferences.accent.value===preset"
              @click="uiPreferences.accent.value=preset">
              {{preset==='graphite'?(uiPreferences.locale.value==='ru'?'Графит':'Graphite'):
                preset==='indigo'?(uiPreferences.locale.value==='ru'?'Индиго':'Indigo'):(uiPreferences.locale.value==='ru'?'Янтарь':'Amber')}}
            </Button>
          </div>
          <p class="text-xs leading-5 text-muted-foreground">{{uiPreferences.locale.value==='ru'?'Настройки оформления локальны и не меняют права доступа.':'Appearance is local and does not change access rights.'}}</p>
        </fieldset>
        <div class="max-w-sm space-y-2 text-sm">
          <p class="font-semibold">{{t('settings.density')}}</p>
          <Select :model-value="uiPreferences.density.value" @update:model-value="densityChanged">
            <SelectTrigger class="min-h-10" :aria-label="t('settings.density')"><SelectValue/></SelectTrigger>
            <SelectContent>
              <SelectItem value="compact">{{t('common.compact')}}</SelectItem>
              <SelectItem value="comfortable">{{t('common.comfortable')}}</SelectItem>
            </SelectContent>
          </Select>
        </div>
        <div class="max-w-sm space-y-2 text-sm">
          <p class="font-semibold">{{t('platform.displayTimeZone')}}</p>
          <Select :model-value="uiPreferences.displayTimeZone.value" @update:model-value="zoneChanged">
            <SelectTrigger class="min-h-10" :aria-label="t('platform.displayTimeZone')"><SelectValue/></SelectTrigger>
            <SelectContent>
              <SelectItem value="system">{{t('platform.deviceTimeZone')}}</SelectItem>
              <SelectItem value="UTC">UTC</SelectItem>
            </SelectContent>
          </Select>
          <p class="text-xs leading-5 text-muted-foreground">{{t('platform.displayTimeZoneHint')}}</p>
        </div>
      </CardContent>
    </Card>

    <Card>
      <CardHeader><CardTitle class="text-base">{{t('platform.browserDiagnostics')}}</CardTitle></CardHeader>
      <CardContent class="space-y-4">
        <div class="flex items-center gap-3">
          <Switch :model-value="uiPreferences.diagnosticsConsent.value"
            :aria-label="t('platform.browserDiagnosticsConsent')"
            @update:model-value="enabled=>uiPreferences.diagnosticsConsent.value=enabled"/>
          <span class="text-sm">{{t('platform.browserDiagnosticsConsent')}}</span>
        </div>
        <p class="text-xs leading-5 text-muted-foreground">{{t('platform.browserDiagnosticsPrivacy')}}</p>
        <p role="status" class="text-xs text-muted-foreground">
          {{t('platform.browserDiagnosticsCount',{count:browserTelemetry.state.buffered})}}
          · {{t('platform.browserDiagnosticsNoRelay')}}
        </p>
        <Button variant="outline" size="sm" @click="browserTelemetry.clear()">{{t('platform.clearDiagnostics')}}</Button>
      </CardContent>
    </Card>
    <OwnerReadinessPanel v-if="projectContext.state.user?.active" />
    <Card>
      <CardHeader><CardTitle class="text-base">{{t('platform.serverSettings')}}</CardTitle></CardHeader>
      <CardContent class="space-y-3">
        <p role="status" class="text-sm text-muted-foreground">{{t('platform.cutoverDisabled')}}</p>
        <p class="text-xs text-muted-foreground">{{t('platform.cutoverSource')}}: {{platformCutoverReadiness.acceptedSource}}</p>
        <p class="text-xs text-muted-foreground">{{t('platform.uiPackageVersion')}}: {{uiPackageVersion}}</p>
        <p class="text-xs text-muted-foreground">{{t('platform.environmentNotVerified')}}</p>
        <h3 class="text-sm font-medium">{{t('platform.cutoverRequirements')}}</h3>
        <ul class="list-inside list-disc space-y-1 text-xs text-muted-foreground">
          <li v-for="condition in platformCutoverReadiness.missing" :key="condition">{{t(`platform.cutoverPrerequisites.${condition}`)}}</li>
        </ul>
        <p class="text-xs text-muted-foreground">{{t('platform.cutoverNoLocalOverride')}}</p>
      </CardContent>
    </Card>
  </div>
</template>
