<script setup lang="ts">
import { computed, onBeforeUnmount, ref, watch } from "vue"
import { decodeFilesReadResult, type FilesReadDecode } from "../model/read-result"
import { buildTextPreview, findTextMatches, pageForMatch } from "../model/text-window"
import { useI18n } from "vue-i18n"
import { FileText, LockKeyhole } from "lucide-vue-next"
import { Card, CardContent, CardHeader, CardTitle } from "@/shared/ui/card"
import { Badge } from "@/shared/ui/badge"
import { Button } from "@/shared/ui/button"
import { Input } from "@/shared/ui/input"

const props=withDefaults(defineProps<{
  path?:string
  content?:string
  /** Bounded future owner response, supplied only after an authorized BFF read.
   * Local design text uses content instead; neither prop grants permission. */
  readResult?:unknown
  /** Never accept raw local content as a production file read. */
  designPreview?:boolean
  status?:"empty"|"loading"|"ready"|"denied"|"unavailable"
}>(),{status:"empty"})
const {locale}=useI18n()
const labels=computed(()=>locale.value==="ru"?{
 title:"Предпросмотр файла",empty:"Выберите файл из авторизованного списка. Содержимое появится только после чтения через Control Panel API.",
 loading:"Получаем содержимое файла…",denied:"Нет разрешения на чтение файла.",
 unavailable:"Backend предпросмотра не подключён.",truncated:"Отображён только ограниченный фрагмент текста.",
 text:"Текст",binaryTag:"Двоичный файл",binary:"Двоичный формат не отображается как текст.",
 bytes:"Байт",checksum:"SHA-256 содержимого",page:"Фрагмент",lines:"Строки",previous:"Предыдущий фрагмент",next:"Следующий фрагмент",
 search:"Найти в тексте (с учётом регистра)",matches:"Совпадения",noMatches:"Совпадений нет",previousMatch:"Предыдущее совпадение",nextMatch:"Следующее совпадение",
 invalid:"Ответ Files не прошёл проверку пути, размера или контрольной суммы.",
}:{
 title:"File preview",empty:"Select a file from an authorized listing. Content appears only after a Control Panel API read.",
 loading:"Loading file content…",denied:"File read permission denied.",
 unavailable:"Preview backend is not connected.",truncated:"Only a bounded excerpt is shown.",
 text:"Text",binaryTag:"Binary file",binary:"Binary content cannot be displayed as text.",
 bytes:"Bytes",checksum:"Content SHA-256",page:"Excerpt",lines:"Lines",previous:"Previous excerpt",next:"Next excerpt",
 search:"Find in text (case-sensitive)",matches:"Matches",noMatches:"No matches",previousMatch:"Previous match",nextMatch:"Next match",
 invalid:"Files response failed path, size or checksum validation.",
})
const decoded=ref<FilesReadDecode|null>(null)
let generation=0
let controller:AbortController|null=null
watch(()=>[props.status,props.path,props.readResult],()=>{
  const run=++generation
  controller?.abort();controller=null;decoded.value=null
  if(props.status!=="ready"||props.readResult===undefined)return
  if(!props.path){decoded.value={kind:"invalid"};return}
  const request=new AbortController()
  controller=request
  void decodeFilesReadResult(props.readResult,props.path,request.signal).then(result=>{
    if(run===generation&&!request.signal.aborted)decoded.value=result
  })
},{immediate:true,flush:"sync"})
onBeforeUnmount(()=>{++generation;controller?.abort();decoded.value=null})
const effectiveStatus=computed(()=>{
  if(props.status!=="ready")return props.status
  if(props.readResult===undefined)return import.meta.env.DEV&&props.designPreview&&typeof props.content==="string"?"ready":"invalid"
  return !decoded.value?"loading":decoded.value.kind==="text"?"ready":
    decoded.value.kind==="cancelled"?"loading":decoded.value.kind
})
const content=computed(()=>props.readResult===undefined?(import.meta.env.DEV&&props.designPreview?props.content:undefined):
  decoded.value?.kind==="text"?decoded.value.content:undefined)
const preview=computed(()=>buildTextPreview(effectiveStatus.value==="ready"?content.value??"":""))
const pageIndex=ref(0),query=ref(""),matchIndex=ref(0)
const matches=computed(()=>findTextMatches(preview.value.text,query.value))
const page=computed(()=>preview.value.pages[pageIndex.value]??preview.value.pages[0]!)
const metadata=computed(()=>decoded.value?.kind==="text"||decoded.value?.kind==="binary"?decoded.value:null)
const highlight=computed(()=>{
  const current=page.value,text=preview.value.text.slice(current.start,current.end)
  const at=matches.value.positions[matchIndex.value]
  if(at===undefined||at<current.start||at>=current.end)return {before:text,match:"",after:""}
  const relative=at-current.start,end=Math.min(text.length,relative+query.value.length)
  return {before:text.slice(0,relative),match:text.slice(relative,end),after:text.slice(end)}
})
function moveMatch(delta:number):void{
  const count=matches.value.positions.length
  if(!count)return
  matchIndex.value=(matchIndex.value+delta+count)%count
  pageIndex.value=pageForMatch(preview.value.pages,matches.value.positions[matchIndex.value]!)
}
watch(()=>[props.path,props.status,props.readResult,props.content],()=>{
  query.value="";pageIndex.value=0;matchIndex.value=0
},{flush:"sync"})
watch(query,()=>{
  matchIndex.value=0
  pageIndex.value=pageForMatch(preview.value.pages,matches.value.positions[0]??0)
})
const caption=computed(()=>effectiveStatus.value==="loading"?labels.value.loading:
  effectiveStatus.value==="denied"?labels.value.denied:effectiveStatus.value==="unavailable"?labels.value.unavailable:
  effectiveStatus.value==="binary"?labels.value.binary:effectiveStatus.value==="invalid"?labels.value.invalid:labels.value.empty)
</script>
<template>
  <Card class="min-w-0">
    <CardHeader class="flex flex-row flex-wrap items-center justify-between gap-2">
      <CardTitle class="flex items-center gap-2 text-sm"><FileText class="size-4"/>{{labels.title}}</CardTitle>
      <Badge variant="outline">{{effectiveStatus==='binary'?labels.binaryTag:effectiveStatus==='ready'?labels.text:'Files'}}</Badge>
    </CardHeader>
    <CardContent>
      <div v-if="effectiveStatus==='ready'" class="min-w-0 space-y-3">
        <p class="break-all font-mono text-xs text-muted-foreground">{{path}}</p>
        <div class="flex min-w-0 flex-wrap items-center gap-2">
          <Input v-model="query" class="min-w-0 flex-1 basis-52" maxlength="128" :aria-label="labels.search" :placeholder="labels.search" @keydown.enter.prevent="moveMatch(1)"/>
          <Button variant="outline" size="sm" :disabled="!matches.positions.length" @click="moveMatch(-1)" :aria-label="labels.previousMatch">↑</Button>
          <Button variant="outline" size="sm" :disabled="!matches.positions.length" @click="moveMatch(1)" :aria-label="labels.nextMatch">↓</Button>
        </div>
        <p v-if="query" class="text-xs text-muted-foreground" role="status">{{matches.positions.length?`${labels.matches}: ${matchIndex+1} / ${matches.positions.length}${matches.limited?'+':''}`:labels.noMatches}}</p>
        <pre class="max-h-[420px] overflow-auto rounded-lg border border-border bg-muted/30 p-4 text-xs leading-5 text-foreground" tabindex="0">{{highlight.before}}<mark v-if="highlight.match" class="bg-accent text-accent-foreground">{{highlight.match}}</mark>{{highlight.after}}</pre>
        <div class="flex flex-wrap items-center justify-between gap-2">
          <Button variant="outline" size="sm" :disabled="pageIndex===0" @click="pageIndex--">{{labels.previous}}</Button>
          <p class="text-xs text-muted-foreground" role="status">{{labels.page}} {{pageIndex+1}} / {{preview.pages.length}} · {{labels.lines}} {{page.firstLine}}–{{page.lastLine}}</p>
          <Button variant="outline" size="sm" :disabled="pageIndex+1>=preview.pages.length" @click="pageIndex++">{{labels.next}}</Button>
        </div>
        <p v-if="preview.truncated" class="text-xs text-muted-foreground">{{labels.truncated}}</p>
      </div>
      <div v-else class="flex min-h-40 flex-col items-center justify-center gap-3 rounded-lg border border-dashed border-border px-4 text-center" role="status">
        <LockKeyhole class="size-5 text-muted-foreground" aria-hidden="true"/>
        <p class="max-w-md text-sm text-muted-foreground">{{caption}}</p>
      </div>
      <div v-if="metadata" class="mt-3 space-y-2 text-xs text-muted-foreground">
        <p v-if="effectiveStatus==='binary'" class="break-all font-mono">{{metadata.path}}</p>
        <p>{{labels.bytes}}: {{metadata.sizeBytes.toLocaleString(locale)}}</p>
        <details><summary class="cursor-pointer">{{labels.checksum}}</summary><p class="mt-1 break-all font-mono">{{metadata.sha256}}</p></details>
      </div>
    </CardContent>
  </Card>
</template>
