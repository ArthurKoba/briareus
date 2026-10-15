<script setup lang="ts">
import { computed } from "vue"
import { useI18n } from "vue-i18n"
import { Activity, Boxes, Database, GitBranch, HardDrive, ShieldAlert } from "lucide-vue-next"
import { Badge } from "@/shared/ui/badge"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/shared/ui/card"
import { Skeleton } from "@/shared/ui/skeleton"

const props=withDefaults(defineProps<{state?:"empty"|"loading"|"denied"|"unavailable"}>(),{state:"empty"})
const {locale}=useI18n()
const ru=computed(()=>locale.value==="ru")
const words=computed(()=>ru.value?{
 title:"Состояние инфраструктуры",description:"Сводка MCP, интеграций, анализа и рабочих пространств",
 source:"Данные должны поступать из авторизованного Control Panel API",
 missing:"Нет подтверждённых данных",loading:"Получение сведений…",
 denied:"Нет подтверждённого доступа",unavailable:"Источник недоступен",
 calls:"Вызовы MCP",latency:"Задержка инструментов",integrations:"Подключения",
 sessions:"OAuth-сессии",analysis:"Проекты анализа",workers:"Задания анализа",
 workspace:"Рабочие пространства",free:"Свободное место",
 mcp:"MCP",providers:"Интеграции",reverse:"Анализ",storage:"Рабочая среда",
}:{
 title:"Infrastructure overview",description:"MCP tools, integrations, analysis and workspace activity",
 source:"Metrics require the authorized Control Panel API",
 missing:"No verified data",loading:"Fetching information…",
 denied:"No verified access",unavailable:"Source unavailable",
 calls:"MCP calls",latency:"Tool latency",integrations:"Connections",
 sessions:"OAuth sessions",analysis:"Analysis projects",workers:"Analysis jobs",
 workspace:"Workspaces",free:"Free storage",
 mcp:"MCP",providers:"Integrations",reverse:"Analysis",storage:"Workspaces",
})
const groups=computed(()=>[
  {id:"mcp",title:words.value.mcp,icon:Activity,items:[words.value.calls,words.value.latency]},
  {id:"integrations",title:words.value.providers,icon:GitBranch,items:[words.value.integrations,words.value.sessions]},
  {id:"analysis",title:words.value.reverse,icon:Database,items:[words.value.analysis,words.value.workers]},
  {id:"workspace",title:words.value.storage,icon:HardDrive,items:[words.value.workspace,words.value.free]},
])
const status=computed(()=>props.state==="loading"?words.value.loading:props.state==="denied"?words.value.denied:props.state==="unavailable"?words.value.unavailable:words.value.missing)
</script>
<template>
  <div class="space-y-6">
    <header class="flex flex-wrap items-start justify-between gap-3">
      <div class="space-y-2">
        <h2 class="text-2xl font-semibold tracking-tight">{{words.title}}</h2>
        <p class="text-sm text-muted-foreground">{{words.description}}</p>
      </div>
      <Badge variant="outline" class="gap-1"><ShieldAlert class="size-3.5"/>{{status}}</Badge>
    </header>
    <section v-for="group in groups" :key="group.id" class="space-y-3" :aria-labelledby="'dashboard-'+group.id">
      <div class="flex items-center gap-2">
        <component :is="group.icon" class="size-4 text-muted-foreground" aria-hidden="true"/>
        <h3 :id="'dashboard-'+group.id" class="text-sm font-semibold">{{group.title}}</h3>
      </div>
      <div class="grid gap-3 md:grid-cols-2">
        <Card v-for="label in group.items" :key="label" class="min-w-0 rounded-xl">
          <CardHeader class="pb-3">
            <CardDescription class="text-xs font-semibold uppercase tracking-wide">{{label}}</CardDescription>
            <CardTitle class="text-2xl tabular-nums">
              <Skeleton v-if="state==='loading'" class="h-8 w-24"/>
              <span v-else aria-label="No verified value">—</span>
            </CardTitle>
          </CardHeader>
          <CardContent class="min-h-5 pt-0 text-xs text-muted-foreground">
            {{status}}
          </CardContent>
        </Card>
      </div>
    </section>
    <p class="flex items-start gap-2 border-t border-border pt-4 text-xs leading-5 text-muted-foreground">
      <Boxes class="mt-0.5 size-4 shrink-0" aria-hidden="true"/>{{words.source}}
    </p>
  </div>
</template>
