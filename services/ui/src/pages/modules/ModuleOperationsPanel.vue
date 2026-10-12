<script setup lang="ts">
import { computed, ref } from "vue"
import { ArrowLeft, ArrowRight, Download, ExternalLink, FolderPlus, Github, Globe2, Monitor, Plus, RefreshCw, ShieldAlert, SquareTerminal, Trash2, Upload } from "lucide-vue-next"
import { useUiPreferences } from "@/shared/lib/preferences"
import type { ModuleId } from "@/features/modules/catalog"

/** The historical Admin UI had real BrowserPage, FilesPage, TerminalPage,
 * GitPage and CallsPage. This surface conserves their UX structure without
 * reviving the old Management API, native passwords or provider WebSockets.
 * Disabled controls turn into authorized BFF actions only after real DTOs exist.
 */
const props=defineProps<{ module:ModuleId }>()
const lang=computed(()=>useUiPreferences().locale.value)
const isRu=computed(()=>lang.value==="ru")
const browserMode=ref<"managed"|"external">("managed")
const captions=computed(()=>isRu.value?{
  managed:"Управляемый",external:"Внешний",tabs:"Вкладки",emptyTabs:"Подтверждённых вкладок нет",address:"Адрес страницы",noStream:"Трансляция экрана недоступна без авторизованного WebSocket от Control Panel API",pageActions:"Навигация и вкладки",newTab:"Новая вкладка",reload:"Обновить",back:"Назад",forward:"Вперёд",screenshot:"Снимок экрана",devtools:"DevTools",notAvailable:"Нет авторизованных данных от Control Panel API",refresh:"Обновить",upload:"Загрузить",newFolder:"Создать папку",delete:"Удалить",download:"Скачать",files:"Файлы и каталоги",name:"Имя",type:"Тип",size:"Размер",actions:"Действия",jobs:"Задания",workspaces:"Рабочие пространства",terminal:"Интерактивный терминал",start:"Запустить",stop:"Остановить",output:"Вывод задания",gitAccounts:"Аккаунты и репозитории",account:"Аккаунт",repository:"Репозиторий",branch:"Ветка",pulls:"Pull / Merge requests",pipelines:"CI/CD",noAuth:"Требуется подтверждённая сессия и права управления",tableEmpty:"Нет подтверждённых серверных записей",filters:"Фильтры",connect:"Подключить",session:"Сессия",status:"Состояние",history:"История",detail:"Детали",timestamp:"Время",source:"Источник",applicable:"Ожидается серверный API-контракт"
}:{
  managed:"Managed",external:"External",tabs:"Tabs",emptyTabs:"No verified tabs",address:"Page address",noStream:"Screen streaming is unavailable without an authorized Control Panel API WebSocket",pageActions:"Navigation and tabs",newTab:"New tab",reload:"Reload",back:"Back",forward:"Forward",screenshot:"Screenshot",devtools:"DevTools",notAvailable:"No authorized data from Control Panel API",refresh:"Refresh",upload:"Upload",newFolder:"New folder",delete:"Delete",download:"Download",files:"Files and directories",name:"Name",type:"Type",size:"Size",actions:"Actions",jobs:"Jobs",workspaces:"Workspaces",terminal:"Interactive terminal",start:"Run",stop:"Stop",output:"Job output",gitAccounts:"Accounts and repositories",account:"Account",repository:"Repository",branch:"Branch",pulls:"Pull / Merge requests",pipelines:"CI/CD",noAuth:"Verified session and management permissions required",tableEmpty:"No verified server records",filters:"Filters",connect:"Connect",session:"Session",status:"Status",history:"History",detail:"Details",timestamp:"Time",source:"Source",applicable:"Awaiting verified server API contract"
})
const columns=computed(()=>props.module==="files"?[captions.value.name,captions.value.type,captions.value.size,captions.value.actions]:props.module==="terminal"?[captions.value.workspaces,captions.value.jobs,captions.value.status,captions.value.actions]:props.module==="github"||props.module==="gitlab"?[captions.value.account,captions.value.repository,captions.value.branch,captions.value.pipelines]:[captions.value.timestamp,captions.value.source,captions.value.status,captions.value.detail])
</script>
<template>
  <section class="space-y-4" :aria-label="captions.actions">
    <template v-if="module==='web'">
      <div class="rounded-xl border border-border bg-card p-3 shadow-sm sm:p-4">
        <header class="mb-3 flex flex-wrap items-center justify-between gap-2">
          <div class="inline-flex rounded-lg border border-border p-0.5" role="group" :aria-label="captions.session">
            <button type="button" class="min-h-10 rounded-md px-3 text-sm font-medium focus-visible:outline-2 focus-visible:outline-ring" :class="browserMode==='managed'?'bg-primary text-primary-foreground':'hover:bg-muted'" :aria-pressed="browserMode==='managed'" @click="browserMode='managed'">{{captions.managed}}</button>
            <button type="button" class="min-h-10 rounded-md px-3 text-sm font-medium focus-visible:outline-2 focus-visible:outline-ring" :class="browserMode==='external'?'bg-primary text-primary-foreground':'hover:bg-muted'" :aria-pressed="browserMode==='external'" @click="browserMode='external'">{{captions.external}}</button>
          </div>
          <span class="text-xs text-muted-foreground">{{captions.noAuth}}</span>
        </header>
        <div class="flex min-h-12 items-center gap-2 border-b border-border pb-2 text-sm text-muted-foreground"><Globe2 class="size-4 shrink-0" aria-hidden="true"/><span>{{captions.tabs}} — {{captions.emptyTabs}}</span><button disabled class="ml-auto inline-flex size-9 items-center justify-center rounded-lg border border-border opacity-50" :aria-label="captions.newTab" :title="captions.notAvailable"><Plus class="size-4"/></button></div>
        <div class="mt-3 flex min-w-0 flex-wrap items-center gap-2">
          <button disabled type="button" class="grid size-9 place-items-center rounded-lg border border-border opacity-40" :aria-label="captions.back"><ArrowLeft class="size-4"/></button>
          <button disabled type="button" class="grid size-9 place-items-center rounded-lg border border-border opacity-40" :aria-label="captions.forward"><ArrowRight class="size-4"/></button>
          <button disabled type="button" class="grid size-9 place-items-center rounded-lg border border-border opacity-40" :aria-label="captions.reload"><RefreshCw class="size-4"/></button>
          <label class="min-w-44 flex-1 text-xs text-muted-foreground">{{captions.address}}<input class="field mt-1 text-sm" type="url" readonly disabled :placeholder="captions.notAvailable" autocomplete="off"/></label>
          <button disabled type="button" class="grid size-9 place-items-center rounded-lg border border-border opacity-40" :aria-label="captions.devtools"><ExternalLink class="size-4"/></button>
        </div>
        <div class="mt-3 flex min-h-48 flex-col items-center justify-center gap-3 rounded-xl border border-dashed border-border bg-muted/20 px-4 py-8 text-center sm:min-h-72">
          <Monitor class="size-9 text-muted-foreground" aria-hidden="true"/>
          <p class="max-w-md text-sm text-muted-foreground">{{captions.noStream}}</p>
          <div class="flex flex-wrap justify-center gap-2"><button disabled class="rounded-lg border border-border px-3 py-2 text-xs opacity-50">{{captions.screenshot}}</button><button disabled class="rounded-lg border border-border px-3 py-2 text-xs opacity-50">{{captions.connect}}</button></div>
        </div>
      </div>
    </template>
    <template v-else-if="module==='terminal'">
      <div class="settings-card space-y-3"><h4 class="flex items-center gap-2 font-semibold"><SquareTerminal class="size-4" aria-hidden="true"/>{{captions.terminal}}</h4><div class="flex flex-wrap items-center gap-2"><button disabled class="rounded-lg border border-border px-3 py-2 text-xs opacity-50">{{captions.start}}</button><button disabled class="rounded-lg border border-border px-3 py-2 text-xs opacity-50">{{captions.stop}}</button><span class="text-xs text-muted-foreground">{{captions.noAuth}}</span></div><pre class="min-h-32 overflow-auto rounded-lg bg-[#14202c] p-4 text-xs text-slate-300" aria-label="Terminal output">{{captions.notAvailable}}</pre></div>
    </template>
    <template v-else-if="module==='files'">
      <div class="flex flex-wrap items-center gap-2"><button disabled class="inline-flex items-center gap-1 rounded-lg border border-border px-3 py-2 text-xs opacity-50"><Upload class="size-4"/>{{captions.upload}}</button><button disabled class="inline-flex items-center gap-1 rounded-lg border border-border px-3 py-2 text-xs opacity-50"><FolderPlus class="size-4"/>{{captions.newFolder}}</button><button disabled class="inline-flex items-center gap-1 rounded-lg border border-border px-3 py-2 text-xs opacity-50"><Download class="size-4"/>{{captions.download}}</button><button disabled class="inline-flex items-center gap-1 rounded-lg border border-border px-3 py-2 text-xs opacity-50"><Trash2 class="size-4"/>{{captions.delete}}</button></div>
    </template>
    <template v-else-if="module==='github'||module==='gitlab'">
      <div class="rounded-xl border border-border bg-muted/20 p-4"><h4 class="flex items-center gap-2 font-semibold"><Github class="size-4" aria-hidden="true"/>{{captions.gitAccounts}}</h4><p class="mt-2 text-xs text-muted-foreground">{{captions.noAuth}}</p><div class="mt-3 flex flex-wrap gap-2"><button disabled class="rounded-lg border border-border px-3 py-2 text-xs opacity-50">{{captions.pulls}}</button><button disabled class="rounded-lg border border-border px-3 py-2 text-xs opacity-50">{{captions.pipelines}}</button><button disabled class="rounded-lg border border-border px-3 py-2 text-xs opacity-50">{{captions.connect}}</button></div></div>
    </template>
    <div class="overflow-x-auto rounded-xl border border-border" role="region" :aria-label="captions.history">
      <table class="w-full min-w-[480px] text-left text-xs">
        <thead class="border-b border-border bg-muted/40 text-muted-foreground"><tr><th v-for="column in columns" :key="column" scope="col" class="px-3 py-3 font-semibold">{{column}}</th></tr></thead>
        <tbody><tr><td :colspan="columns.length" class="px-4 py-10 text-center text-sm text-muted-foreground"><ShieldAlert class="mx-auto mb-2 size-5" aria-hidden="true"/>{{captions.tableEmpty}}<p class="mt-1 text-xs">{{captions.applicable}}</p></td></tr></tbody>
      </table>
    </div>
  </section>
</template>
