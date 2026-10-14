<script setup lang="ts">
import { computed, ref, watch } from "vue"
import { ArrowLeft, ChevronRight, CircleAlert, Monitor, Settings2, WifiOff } from "lucide-vue-next"
import { useUiPreferences } from "@/shared/lib/preferences"
import { setLocale } from "@/shared/i18n"
import ModuleOperationsPanel from "@/pages/modules/ModuleOperationsPanel.vue"
import { moduleById, modules, type ModuleId, type ModuleSetting, type ModuleView } from "@/features/modules/catalog"
import Button from "@/shared/ui/Button.vue"

const props=withDefaults(defineProps<{initial?:ModuleId; preview?:boolean}>(),{initial:"web",preview:false})
const emit=defineEmits<{close:[]}>()
const prefs=useUiPreferences()
const lang=computed(() => prefs.locale.value)
const selected=ref<ModuleId>(props.initial)
const view=ref<ModuleView>("overview")
const module=computed(()=>moduleById(selected.value) ?? modules[0]!)
const values=ref<Record<string,string|boolean>>({})
const touched=ref(false)
function selectModule(id:ModuleId):void {selected.value=id;view.value="overview"}
watch([selected,view],()=>{values.value={};touched.value=false})
const words=computed(()=>lang.value==="ru"?{
  title:"Модули MCP",preview:"Открытый обзор модулей — без серверных полномочий",back:"Вход и доступ",overview:"Операции",settings:"Настройки модуля",general:"Общие настройки",globalHint:"Язык, тема, плотность и часовой пояс относятся ко всему Briareus",moduleHint:"Параметры отдельного модуля не влияют на остальные сервисы",backend:"Подключение Control Panel API",unavailable:"Серверный контракт модуля не подключён. Данные, WebSocket и операции недоступны.",noData:"Нет подтверждённых серверных записей",capabilities:"Возможности",configure:"Параметры сервера",pending:"Изменения не отправлены. Применение доступно только после подтверждённого API-контракта и прав пользователя.",save:"Применить настройки",unsupported:"Недоступно до подключения Control Panel API",connection:"Состояние подключения",offline:"Не подключено",tabs:"Вкладки и сеансы",emptyTabs:"Нет полученных вкладок браузера",actions:"Операции",files:"Путь / Тип / Размер / Действия",jobs:"Рабочее пространство / Задание / Состояние",git:"Аккаунт / Репозиторий / Ветка",scope:"Область доступа",source:"Источник данных: Control Panel API",external:"Внешние учётные данные и секреты не сохраняются в браузере",choose:"Выберите значение",inspect:"Обзор",gitRecords:"Нет подтверждённых аккаунтов и репозиториев",close:"Закрыть",denied:"Контролы изменяют только черновик формы, серверные значения не меняются",filter:"Поиск среди модулей",moduleType:"MCP / служебный модуль"
}: {
  title:"MCP modules",preview:"Public module overview — no server privileges",back:"Sign in / access",overview:"Operations",settings:"Module settings",general:"Global settings",globalHint:"Language, theme, density and time zone apply across Briareus",moduleHint:"Module-specific settings do not alter other services",backend:"Control Panel API connection",unavailable:"The module's server contract is not connected. Data, WebSocket and actions are unavailable.",noData:"No verified server records",capabilities:"Capabilities",configure:"Server-owned parameters",pending:"Changes have not been sent. Applying settings requires an accepted API contract and verified user permissions.",save:"Apply settings",unsupported:"Unavailable until Control Panel API is connected",connection:"Connection status",offline:"Not connected",tabs:"Tabs and sessions",emptyTabs:"No browser tabs received",actions:"Operations",files:"Path / Type / Size / Actions",jobs:"Workspace / Job / Status",git:"Account / Repository / Branch",scope:"Access scope",source:"Data source: Control Panel API",external:"External credentials and secrets are not stored in the browser",choose:"Choose a value",inspect:"Overview",gitRecords:"No verified accounts or repositories",close:"Close",denied:"Controls only edit the form draft, not server values",filter:"Search modules",moduleType:"MCP / service module"
})
const filter=ref("")
const visible=computed(()=>modules.filter(m=>`${m.title.en} ${m.title.ru} ${m.summary.en} ${m.summary.ru}`.toLocaleLowerCase().includes(filter.value.toLocaleLowerCase().trim())))
function onSetting(event:Event, field:ModuleSetting):void {
 const input=event.target as HTMLInputElement|HTMLSelectElement
 values.value={...values.value,[field.key]:field.kind==="toggle"?(input as HTMLInputElement).checked:input.value}
 touched.value=true
}
function selectedSetting(field:ModuleSetting):string|boolean {return values.value[field.key]??(field.kind==="toggle"?false:"")}
</script>
<template>
  <section class="mx-auto w-full max-w-[1440px] space-y-5 rounded-[22px] border border-border bg-card p-3 shadow-sm sm:p-6" :aria-label="words.title">
    <header class="flex flex-wrap items-start justify-between gap-3 border-b border-border pb-4">
      <div class="flex min-w-0 flex-wrap items-center gap-3">
        <div class="grid size-10 shrink-0 place-items-center rounded-xl bg-primary/10 text-primary"><Monitor class="size-5" aria-hidden="true" /></div>
        <div class="min-w-0"><h2 class="text-lg font-semibold text-foreground">{{words.title}}</h2><p class="text-xs text-muted-foreground">{{words.source}}</p></div>
      </div>
      <Button v-if="preview" variant="outline" size="sm" @click="emit('close')"><ArrowLeft class="mr-2 size-4" aria-hidden="true"/>{{words.back}}</Button>
    </header>
    <p v-if="preview" role="status" class="rounded-xl border border-border bg-muted/40 px-4 py-3 text-sm text-muted-foreground"><CircleAlert class="mr-2 inline size-4 align-middle" aria-hidden="true"/>{{words.preview}}. {{words.unavailable}}</p>
    <div class="grid min-w-0 gap-5 lg:grid-cols-[240px_minmax(0,1fr)]">
      <nav class="min-w-0 space-y-2" :aria-label="words.title">
        <label class="block text-xs font-semibold text-muted-foreground">{{words.filter}}<input v-model="filter" type="search" class="field mt-2" maxlength="100" :placeholder="words.filter"/></label>
        <div class="grid grid-cols-2 gap-1 sm:grid-cols-3 lg:grid-cols-1">
          <button v-for="item in visible" :key="item.id" type="button" class="flex min-h-11 min-w-0 items-center justify-between gap-2 rounded-lg px-3 py-2 text-left text-sm transition focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-ring" :class="item.id===selected?'bg-primary/10 font-semibold text-primary':'hover:bg-muted text-foreground'" :aria-current="item.id===selected?'page':undefined" @click="selectModule(item.id)">
            <span class="truncate">{{item.title[lang]}}</span><ChevronRight class="size-3.5 shrink-0 opacity-60" aria-hidden="true" />
          </button>
        </div>
        <p v-if="visible.length===0" class="p-2 text-xs text-muted-foreground">{{words.noData}}</p>
      </nav>
      <article class="min-w-0 space-y-5">
        <div class="flex min-w-0 flex-wrap items-start justify-between gap-2">
          <div class="min-w-0"><p class="text-[11px] font-semibold uppercase tracking-wider text-muted-foreground">{{words.moduleType}}</p><h3 class="mt-1 break-words text-xl font-semibold text-foreground">{{module.title[lang]}}</h3><p class="mt-2 max-w-2xl text-sm text-muted-foreground">{{module.summary[lang]}}</p></div>
          <span class="inline-flex items-center gap-1.5 rounded-full border border-border bg-muted/30 px-3 py-1 text-xs text-muted-foreground"><WifiOff class="size-3.5" aria-hidden="true"/>{{words.offline}}</span>
        </div>
        <div class="flex flex-wrap gap-1 border-b border-border pb-2" role="tablist" :aria-label="module.title[lang]">
          <button type="button" role="tab" class="min-h-11 rounded-lg px-4 text-sm font-medium focus-visible:outline-2 focus-visible:outline-ring" :aria-selected="view==='overview'" :class="view==='overview'?'bg-primary text-primary-foreground':'hover:bg-muted'" @click="view='overview'">{{words.overview}}</button>
          <button type="button" role="tab" class="min-h-11 rounded-lg px-4 text-sm font-medium focus-visible:outline-2 focus-visible:outline-ring" :aria-selected="view==='settings'" :class="view==='settings'?'bg-primary text-primary-foreground':'hover:bg-muted'" @click="view='settings'"><Settings2 class="mr-1 inline size-4" aria-hidden="true"/>{{words.settings}}</button>
          <button type="button" role="tab" class="min-h-11 rounded-lg px-4 text-sm font-medium focus-visible:outline-2 focus-visible:outline-ring" :aria-selected="view==='global'" :class="view==='global'?'bg-primary text-primary-foreground':'hover:bg-muted'" @click="view='global'">{{words.general}}</button>
        </div>
        <div v-if="view==='overview'" class="space-y-5" role="tabpanel">
          <section class="settings-card space-y-3">
            <h4 class="text-sm font-semibold">{{words.capabilities}}</h4>
            <div class="grid gap-2 sm:grid-cols-2">
              <div v-for="(capability,i) in module.features" :key="i" class="flex gap-2 rounded-xl border border-border bg-muted/20 p-3 text-sm text-foreground"><span class="mt-1 size-1.5 shrink-0 rounded-full bg-primary" aria-hidden="true"/><span>{{capability[lang]}}</span></div>
            </div>
          </section>
          <ModuleOperationsPanel :module="selected" />
          <section class="settings-card space-y-3">
            <h4 class="text-sm font-semibold">{{words.connection}}</h4>
            <p class="text-sm text-muted-foreground" role="status">{{words.unavailable}}</p>
          </section>
        </div>
        <div v-else-if="view==='settings'" class="space-y-4" role="tabpanel">
          <div class="rounded-xl border border-border bg-muted/30 p-4"><h4 class="font-semibold">{{words.settings}}</h4><p class="mt-1 text-sm text-muted-foreground">{{words.moduleHint}}. {{words.external}}</p></div>
          <form class="settings-card space-y-4" @submit.prevent>
            <fieldset class="space-y-4"><legend class="mb-2 text-sm font-semibold">{{words.configure}}</legend>
              <label v-for="field in module.settings" :key="field.key" class="block space-y-1.5 text-sm"><span class="font-semibold">{{field.label[lang]}}</span><span class="block text-xs text-muted-foreground">{{field.description[lang]}}</span>
                <select v-if="field.kind==='select'" class="field" :value="selectedSetting(field)" @change="onSetting($event,field)"><option value="">{{words.choose}}</option><option v-for="option in field.options" :key="option" :value="option">{{option}}</option></select>
                <input v-else-if="field.kind==='toggle'" type="checkbox" class="size-5 accent-primary" :checked="Boolean(selectedSetting(field))" @change="onSetting($event,field)" />
                <input v-else class="field" :type="field.kind==='number'?'number':'text'" :min="field.kind==='number'?1:undefined" :maxlength="field.kind==='text'?160:undefined" autocomplete="off" :value="selectedSetting(field)" @input="onSetting($event,field)" />
              </label>
            </fieldset>
            <div class="space-y-2 border-t border-border pt-4"><p role="status" class="text-xs text-muted-foreground">{{touched?words.pending:words.denied}}</p><Button type="button" size="sm" disabled :title="words.unsupported">{{words.save}}</Button></div>
          </form>
        </div>
        <div v-else class="space-y-5" role="tabpanel">
          <div class="settings-card space-y-4">
            <h4 class="text-base font-semibold">{{words.general}}</h4>
            <p class="text-sm text-muted-foreground">{{words.globalHint}}</p>
            <label class="block max-w-sm text-sm font-semibold">{{lang==='ru'?'Язык интерфейса':'Interface language'}}
              <select class="field mt-2" :value="prefs.locale.value" @change="(e:Event)=>{const value=(e.target as HTMLSelectElement).value;if(value==='en'||value==='ru')setLocale(value)}"><option value="ru">Русский</option><option value="en">English</option></select>
            </label>
            <label class="block max-w-sm text-sm font-semibold">{{lang==='ru'?'Тема':'Theme'}}
              <select v-model="prefs.theme.value" class="field mt-2"><option value="system">{{lang==='ru'?'Авто':'Auto'}}</option><option value="light">{{lang==='ru'?'Светлая':'Light'}}</option><option value="dark">{{lang==='ru'?'Тёмная':'Dark'}}</option></select>
            </label>
            <label class="block max-w-sm text-sm font-semibold">{{lang==='ru'?'Плотность':'Density'}}
              <select v-model="prefs.density.value" class="field mt-2"><option value="compact">{{lang==='ru'?'Компактно':'Compact'}}</option><option value="comfortable">{{lang==='ru'?'Комфортно':'Comfortable'}}</option></select>
            </label>
            <label class="block max-w-sm text-sm font-semibold">{{lang==='ru'?'Часовой пояс отображения':'Display time zone'}}
              <select v-model="prefs.displayTimeZone.value" class="field mt-2"><option value="system">{{lang==='ru'?'Устройство':'Device'}}</option><option value="UTC">UTC</option></select>
            </label>
          </div>
        </div>
      </article>
    </div>
  </section>
</template>
