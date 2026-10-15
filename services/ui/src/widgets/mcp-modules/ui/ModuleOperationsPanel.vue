<script setup lang="ts">
import { computed } from "vue"
import { ArrowLeft, ArrowRight, Download, ExternalLink, FolderPlus, Github, Globe2, Monitor, Plus, RefreshCw, ShieldAlert, SquareTerminal, Trash2, Upload } from "lucide-vue-next"
import { useUiPreferences } from "@/shared/lib/preferences"
import type { ModuleId } from "@/features/modules/types"
import { FilePreviewPane } from "@/features/files-preview"
import { RepositoryGroupsPanel } from "@/features/repository-groups"
import { ObservabilityPanel } from "@/features/observability"
import { Button } from "@/shared/ui/button"
import { Input } from "@/shared/ui/input"
import { Badge } from "@/shared/ui/badge"
import { Card, CardContent } from "@/shared/ui/card"
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/shared/ui/table"

/** The historical pre-Control-Panel UI had real BrowserPage, FilesPage, TerminalPage,
 * GitPage and CallsPage. This surface conserves their UX structure without
 * reviving the retired management-plane API, native passwords or provider WebSockets.
 * Disabled controls turn into authorized BFF actions only after real DTOs exist.
 */
const props=defineProps<{ module:ModuleId }>()
const lang=computed(()=>useUiPreferences().locale.value)
const isRu=computed(()=>lang.value==="ru")

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
      <Card class="min-w-0 rounded-xl">
        <CardContent class="space-y-4 p-3 sm:p-5">
          <header class="flex flex-wrap items-start justify-between gap-2">
            <div class="flex items-center gap-3">
              <span class="text-sm font-semibold">{{captions.managed}} · {{captions.tabs}}</span>
              <Badge variant="outline">{{captions.emptyTabs}}</Badge>
            </div>
            <details class="max-w-xs text-xs text-muted-foreground">
              <summary class="cursor-pointer rounded-lg px-2 py-2 focus-visible:outline-2 focus-visible:outline-ring">{{captions.external}}</summary>
              <p class="mt-2 leading-5">{{captions.noAuth}}</p>
            </details>
          </header>
          <div class="flex min-h-11 items-center gap-2 border-b border-border pb-3 text-sm text-muted-foreground">
            <Globe2 class="size-4 shrink-0" aria-hidden="true"/>
            <p class="min-w-0 flex-1 text-xs">{{captions.notAvailable}}</p>
            <Button variant="outline" size="icon" disabled
              :aria-label="captions.newTab" :title="captions.notAvailable">
              <Plus class="size-4" aria-hidden="true"/>
            </Button>
          </div>
          <div class="flex min-w-0 flex-wrap items-end gap-2">
            <Button type="button" variant="outline" size="icon" disabled :aria-label="captions.back">
              <ArrowLeft class="size-4" aria-hidden="true"/>
            </Button>
            <Button type="button" variant="outline" size="icon" disabled :aria-label="captions.forward">
              <ArrowRight class="size-4" aria-hidden="true"/>
            </Button>
            <Button type="button" variant="outline" size="icon" disabled :aria-label="captions.reload">
              <RefreshCw class="size-4" aria-hidden="true"/>
            </Button>
            <label class="min-w-44 flex-1 text-xs text-muted-foreground">
              <span>{{captions.address}}</span>
              <Input class="mt-1" type="url" readonly disabled :placeholder="captions.notAvailable" autocomplete="off"/>
            </label>
            <Button type="button" variant="outline" size="icon" disabled :aria-label="captions.devtools">
              <ExternalLink class="size-4" aria-hidden="true"/>
            </Button>
          </div>
          <div class="flex min-h-48 flex-col items-center justify-center gap-3 rounded-xl border border-dashed border-border bg-muted/20 px-4 py-8 text-center sm:min-h-72">
            <Monitor class="size-9 text-muted-foreground" aria-hidden="true"/>
            <p role="status" class="max-w-md text-sm leading-6 text-muted-foreground">{{captions.noStream}}</p>
            <div class="flex flex-wrap justify-center gap-2">
              <Button type="button" variant="outline" size="sm" disabled>{{captions.screenshot}}</Button>
              <Button type="button" variant="outline" size="sm" disabled>{{captions.connect}}</Button>
            </div>
          </div>
        </CardContent>
      </Card>
    </template>
    <template v-else-if="module==='terminal'">
      <Card class="min-w-0 rounded-xl">
        <CardContent class="space-y-4 p-4 sm:p-5">
          <h4 class="flex items-center gap-2 text-sm font-semibold">
            <SquareTerminal class="size-4" aria-hidden="true"/>{{captions.terminal}}
          </h4>
          <div class="flex flex-wrap items-center gap-2">
            <Button type="button" variant="outline" size="sm" disabled>{{captions.start}}</Button>
            <Button type="button" variant="outline" size="sm" disabled>{{captions.stop}}</Button>
            <p class="text-xs text-muted-foreground">{{captions.noAuth}}</p>
          </div>
          <pre class="min-h-32 overflow-auto rounded-lg border border-border bg-muted/30 p-4 text-xs leading-5 text-foreground"
            :aria-label="captions.output">{{captions.notAvailable}}</pre>
        </CardContent>
      </Card>
    </template>
    <template v-else-if="module==='files'">
      <div class="flex flex-wrap items-center gap-2"><Button type="button" size="sm" variant="outline" disabled><Upload class="size-4"/>{{captions.upload}}</Button><Button type="button" size="sm" variant="outline" disabled><FolderPlus class="size-4"/>{{captions.newFolder}}</Button><Button type="button" size="sm" variant="outline" disabled><Download class="size-4"/>{{captions.download}}</Button><Button type="button" size="sm" variant="outline" disabled><Trash2 class="size-4"/>{{captions.delete}}</Button></div>
      <FilePreviewPane status="unavailable" />
    </template>
    <template v-else-if="module==='github'||module==='gitlab'">
      <Card class="min-w-0 rounded-xl">
        <CardContent class="space-y-3 p-4 sm:p-5">
          <h4 class="flex items-center gap-2 text-sm font-semibold">
            <Github class="size-4" aria-hidden="true"/>{{captions.gitAccounts}}
          </h4>
          <p class="text-xs leading-5 text-muted-foreground">{{captions.noAuth}}</p>
          <div class="flex flex-wrap gap-2">
            <Button type="button" variant="outline" size="sm" disabled>{{captions.pulls}}</Button>
            <Button type="button" variant="outline" size="sm" disabled>{{captions.pipelines}}</Button>
            <Button type="button" variant="outline" size="sm" disabled>{{captions.connect}}</Button>
          </div>
        </CardContent>
      </Card>
      <RepositoryGroupsPanel />
    </template>
    <template v-else-if="module==='observability'">
      <ObservabilityPanel />
    </template>
    <div class="overflow-x-auto rounded-xl border border-border" role="region" :aria-label="captions.history">
      <Table class="min-w-[480px] text-left text-xs">
        <TableHeader class="bg-muted/40 text-muted-foreground">
          <TableRow><TableHead v-for="column in columns" :key="column" class="px-3 py-3 text-xs font-semibold">{{column}}</TableHead></TableRow>
        </TableHeader>
        <TableBody>
          <TableRow><TableCell :colspan="columns.length" class="px-4 py-10 text-center text-sm text-muted-foreground">
            <ShieldAlert class="mx-auto mb-2 size-5" aria-hidden="true"/>{{captions.tableEmpty}}
            <p class="mt-1 text-xs">{{captions.applicable}}</p>
          </TableCell></TableRow>
        </TableBody>
      </Table>
    </div>
  </section>
</template>
