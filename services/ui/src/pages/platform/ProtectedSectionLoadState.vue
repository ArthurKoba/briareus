<script setup lang="ts">
import {useI18n} from "vue-i18n"
import {AlertCircle,LoaderCircle} from "lucide-vue-next"
import {Button} from "@/shared/ui/button"
const props=defineProps<{failed?:boolean}>()
const {locale}=useI18n()
const labels={
  ru:{loading:"Загружаем раздел Control Panel…",failed:"Раздел не загрузился. Повторите открытие страницы.",retry:"Обновить страницу"},
  en:{loading:"Loading Control Panel section…",failed:"Unable to load this section. Reload the page to retry.",retry:"Reload page"},
}
const text=()=>locale.value==="ru"?labels.ru:labels.en
function reload():void{window.location.reload()}
</script>
<template>
  <section class="min-w-0 rounded-xl border border-border bg-card px-4 py-8 text-sm text-muted-foreground"
    :role="props.failed?'alert':'status'" aria-live="polite">
    <div class="flex min-w-0 flex-wrap items-center gap-3">
      <AlertCircle v-if="props.failed" class="size-5 shrink-0"/>
      <LoaderCircle v-else class="size-5 shrink-0 animate-spin"/>
      <span>{{props.failed?text().failed:text().loading}}</span>
      <Button v-if="props.failed" type="button" variant="outline" size="sm" @click="reload">{{text().retry}}</Button>
    </div>
  </section>
</template>
