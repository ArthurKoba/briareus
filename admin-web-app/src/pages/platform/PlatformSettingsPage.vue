<script setup lang="ts">
import { useI18n } from "vue-i18n"
import { setLocale } from "@/shared/i18n"
import { uiPreferences } from "@/shared/lib/preferences"
import { platformCutoverReadiness } from "@/features/platform/api/cutover-contract"
import PageHeader from "@/shared/ui/PageHeader.vue"
const {t}=useI18n()
function onLocaleChange(event: Event): void {
  const value=(event.target as HTMLSelectElement).value
  if (value==="en" || value==="ru") setLocale(value)
}
</script>
<template>
  <div class="space-y-6"><PageHeader :title="t('platform.navigation.settings')" :description="t('platform.settingsHint')" />
    <section class="settings-card space-y-4"><h2 class="font-semibold">{{t('settings.interface')}}</h2>
      <label class="block max-w-sm text-xs">{{t('settings.language')}}<select :value="uiPreferences.locale.value" class="field mt-1" @change="onLocaleChange"><option value="en">English</option><option value="ru">Русский</option></select></label>
      <label class="block max-w-sm text-xs">{{t('settings.theme')}}<select v-model="uiPreferences.theme.value" class="field mt-1"><option value="system">{{t('common.system')}}</option><option value="light">{{t('common.light')}}</option><option value="dark">{{t('common.dark')}}</option></select></label>
      <label class="block max-w-sm text-xs">{{t('settings.density')}}<select v-model="uiPreferences.density.value" class="field mt-1"><option value="comfortable">{{t('common.comfortable')}}</option><option value="compact">{{t('common.compact')}}</option></select></label>
    </section>
    <section class="settings-card space-y-3">
      <h2 class="font-semibold">{{t('platform.serverSettings')}}</h2>
      <p role="status" class="text-sm text-muted-foreground">{{t('platform.cutoverDisabled')}}</p>
      <p class="text-xs text-muted-foreground">{{t('platform.cutoverSource') }}: {{platformCutoverReadiness.acceptedSource}}</p>
      <h3 class="text-sm font-medium">{{t('platform.cutoverRequirements')}}</h3>
      <ul class="list-inside list-disc space-y-1 text-xs text-muted-foreground">
        <li v-for="condition in platformCutoverReadiness.missing" :key="condition">{{t(`platform.cutoverPrerequisites.${condition}`)}}</li>
      </ul>
      <p class="text-xs text-muted-foreground">{{t('platform.cutoverNoLocalOverride')}}</p>
    </section>
  </div>
</template>
