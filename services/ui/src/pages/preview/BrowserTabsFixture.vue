<script setup lang="ts">
import { computed, ref } from "vue"
import { useI18n } from "vue-i18n"
import { Globe, MonitorOff, Plus, X } from "lucide-vue-next"
import { Badge } from "@/shared/ui/badge"
import { Button } from "@/shared/ui/button"
import { Card, CardContent, CardHeader, CardTitle } from "@/shared/ui/card"
import { Input } from "@/shared/ui/input"
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/shared/ui/tabs"

interface DesignTab { id: string; title: string; url: string }
const {locale}=useI18n()
const nextId=ref(3)
const tabs=ref<DesignTab[]>([
  {id:"a",title:"Example A",url:"https://example.invalid/a"},
  {id:"b",title:"Example B",url:"https://example.invalid/b"},
])
const selected=ref("a")
const active=computed(()=>tabs.value.find(tab=>tab.id===selected.value))
const words=computed(()=>locale.value==="ru"?{
  title:"Вкладки браузера — локальный пример",fixture:"Только фикстура дизайна",
  add:"Добавить вкладку",close:"Закрыть вкладку",tab:"Вкладка",
  screen:"Видеопоток не подключён. Фикстура не открывает сайты, не создаёт настоящих сессий и не управляет браузером.",
  empty:"Нет вкладок в локальном примере.",
  address:"Пример адреса, без сетевого запроса",
}:{
  title:"Browser tabs — local sample",fixture:"Design fixture only",
  add:"Add tab",close:"Close tab",tab:"Tab",
  screen:"No screen stream connected. This fixture never opens websites, creates actual sessions or controls a browser.",
  empty:"No local sample tabs.",
  address:"Sample address, no network request",
})
function setTab(id:string|number):void{
  if(typeof id==="string"&&tabs.value.some(tab=>tab.id===id))selected.value=id
}
function addTab():void{
  if(tabs.value.length>=12)return
  const id=String(nextId.value++)
  tabs.value=[...tabs.value,{id,title:words.value.tab+" "+id,url:"about:blank"}]
  selected.value=id
}
function closeTab(id:string):void{
  const index=tabs.value.findIndex(tab=>tab.id===id)
  if(index<0)return
  tabs.value=tabs.value.filter(tab=>tab.id!==id)
  if(selected.value===id)selected.value=tabs.value[Math.max(0,index-1)]?.id??""
}
</script>
<template>
  <Card class="border-dashed">
    <CardHeader class="flex flex-row flex-wrap items-start justify-between gap-3">
      <div>
        <CardTitle class="flex items-center gap-2 text-sm"><Globe class="size-4"/>{{words.title}}</CardTitle>
        <Badge variant="outline" class="mt-2">{{words.fixture}}</Badge>
      </div>
      <Button type="button" size="sm" variant="outline" :aria-label="words.add" :disabled="tabs.length>=12" @click="addTab">
        <Plus class="size-4"/>{{words.add}}
      </Button>
    </CardHeader>
    <CardContent>
      <Tabs :model-value="selected" @update:model-value="setTab">
        <div class="w-full overflow-x-auto pb-2">
          <TabsList class="h-auto min-w-max justify-start gap-1">
            <div v-for="tab in tabs" :key="tab.id" class="flex items-center gap-1">
              <TabsTrigger :value="tab.id" class="max-w-[150px]">{{tab.title}}</TabsTrigger>
              <Button type="button" variant="ghost" size="icon-xs" :aria-label="words.close+' '+tab.title" @click="closeTab(tab.id)">
                <X class="size-3" aria-hidden="true" />
              </Button>
            </div>
          </TabsList>
        </div>
        <TabsContent v-for="tab in tabs" :key="tab.id" :value="tab.id" class="space-y-3">
          <Input type="text" :model-value="tab.url" :aria-label="words.address" readonly />
          <div class="flex min-h-44 flex-col items-center justify-center gap-3 rounded-lg border border-dashed border-border bg-muted/10 p-4 text-center">
            <MonitorOff class="size-6 text-muted-foreground" aria-hidden="true" />
            <p class="max-w-md text-sm leading-6 text-muted-foreground">{{words.screen}}</p>
          </div>
        </TabsContent>
        <p v-if="!active" class="py-8 text-center text-sm text-muted-foreground" role="status">{{words.empty}}</p>
      </Tabs>
    </CardContent>
  </Card>
</template>
