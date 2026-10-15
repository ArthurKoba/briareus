<script setup lang="ts">
import { computed } from "vue"
import { useI18n } from "vue-i18n"
import { Activity, LockKeyhole } from "lucide-vue-next"
import { Card,CardContent,CardHeader,CardTitle } from "@/shared/ui/card"
const {locale}=useI18n()
const title=computed(()=>locale.value==="ru"?"Источники наблюдаемости":"Observability sources")
const notice=computed(()=>locale.value==="ru"?
  "Для просмотра метрик, трассировок и логов нужен разрешённый Control Panel API. Состояние сервисов здесь не подменяется тестовыми данными.":
  "Metrics, traces and logs require an authorized Control Panel API. Service status is not simulated.")
</script>
<template>
  <Card>
    <CardHeader><CardTitle class="flex items-center gap-2 text-sm"><Activity class="size-4"/>{{title}}</CardTitle></CardHeader>
    <CardContent class="space-y-3">
      <div v-for="source in ['SigNoz','Coolify']" :key="source" class="flex min-h-12 items-center gap-3 rounded-lg border border-border px-3">
        <span class="flex-1 text-sm font-medium">{{source}}</span><LockKeyhole class="size-4 text-muted-foreground" aria-hidden="true"/>
      </div>
      <p role="status" class="text-xs leading-5 text-muted-foreground">{{notice}}</p>
    </CardContent>
  </Card>
</template>
