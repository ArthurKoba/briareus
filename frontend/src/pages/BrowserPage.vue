<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from "vue"
import { Tag } from "ant-design-vue"
import { managementApi } from "@/shared/api/management"
import Button from "@/shared/ui/Button.vue"
import PageHeader from "@/shared/ui/PageHeader.vue"

type Page = { page_id:string; label?:string; title?:string; url?:string; page_agent_access?:boolean }
type State = { selected_page_id?:string; docked_devtools_page_id?:string; pages?:Page[]; agent_access_enabled?:boolean; developer_access_enabled?:boolean; developer_access_effective?:boolean; can_reopen_closed_tab?:boolean }
const state=ref<State>({}), status=ref("connecting"), message=ref("Connecting to persistent Chromium…"), url=ref("")
const screen=ref<HTMLImageElement|null>(null), devtools=ref<HTMLImageElement|null>(null)
const dims=ref({w:1440,h:900}), devDims=ref({w:1440,h:900})
let ws:WebSocket|null=null, reconnect=0, refresh=0, lastMove=0, devLastMove=0
const pages=computed(()=>state.value.pages??[]), selectedId=computed(()=>state.value.selected_page_id??""), devId=computed(()=>state.value.docked_devtools_page_id??"")
const live=computed(()=>status.value==="live")
function send(payload:Record<string,unknown>){if(ws?.readyState===WebSocket.OPEN)ws.send(JSON.stringify(payload))}
function syncUrl(){const page=pages.value.find(p=>p.page_id===selectedId.value);if(page)url.value=page.url??""}
async function connect(){
  if(ws && (ws.readyState===WebSocket.OPEN || ws.readyState===WebSocket.CONNECTING))return
  status.value="connecting"; message.value="Connecting to persistent Chromium…"
  try{
    const {ticket}=await managementApi.browserTicket(); const scheme=location.protocol==="https:"?"wss:":"ws:"
    ws=new WebSocket(`${scheme}//${location.host}/browser/ws`)
    ws.onopen=()=>ws?.send(JSON.stringify({type:"auth",ticket}))
    ws.onclose=e=>{ws=null;status.value="disconnected";message.value=e.code===4401?"Authorization expired; renewing…":"Live view reconnecting…";clearTimeout(reconnect);reconnect=window.setTimeout(connect,1000)}
    ws.onerror=()=>{status.value="error";message.value="Browser operator connection failed."}
    ws.onmessage=e=>{const m=JSON.parse(e.data);if(m.type==="state"){state.value=m;status.value="live";message.value="Shared control active.";syncUrl()}else if(m.type==="frame"){const target=m.page_id===selectedId.value?screen.value:m.page_id===devId.value?devtools.value:null;if(target)target.src=`data:image/jpeg;base64,${m.data}`;const d=m.page_id===selectedId.value?dims:devDims;if(m.metadata){d.value={w:m.metadata.deviceWidth??d.value.w,h:m.metadata.deviceHeight??d.value.h}}}else if(m.type==="error"){status.value="error";message.value=m.message??"Browser operator error"}}
  }catch(e){status.value="error";message.value=e instanceof Error?e.message:"Browser ticket failed";clearTimeout(reconnect);reconnect=window.setTimeout(connect,3000)}
}
function pointer(img:HTMLImageElement|null,page:string,d:{w:number;h:number},e:MouseEvent,type:string,button="none",click_count=0){if(!img?.src||!page)return;const r=img.getBoundingClientRect();send({type:"mouse",page_id:page,event:type,x:(e.clientX-r.left)*d.w/r.width,y:(e.clientY-r.top)*d.h/r.height,button,click_count})}
function wheel(img:HTMLImageElement|null,page:string,d:{w:number;h:number},e:WheelEvent){if(!img?.src||!page)return;const r=img.getBoundingClientRect();send({type:"mouse",page_id:page,event:"mouseWheel",x:(e.clientX-r.left)*d.w/r.width,y:(e.clientY-r.top)*d.h/r.height,delta_x:e.deltaX,delta_y:e.deltaY});e.preventDefault()}
function key(page:string,e:KeyboardEvent){if(!page)return;if(e.ctrlKey&&e.shiftKey&&e.key.toLowerCase()==="t"){send({type:"reopen_closed_page"});e.preventDefault();return}if(e.ctrlKey||e.altKey||e.metaKey||e.key.length>1){const p=[];if(e.ctrlKey)p.push("Control");if(e.altKey)p.push("Alt");if(e.metaKey)p.push("Meta");if(e.shiftKey&&e.key.length>1)p.push("Shift");p.push(e.key);send({type:"key",page_id:page,key:p.join("+")})}else send({type:"text",page_id:page,text:e.key});e.preventDefault()}
function now(){ return window.performance.now() }
function button(e:MouseEvent){return e.button===2?"right":e.button===1?"middle":"left"}
function setLabel(page:Page,e:Event){send({type:"set_label",page_id:page.page_id,label:(e.target as HTMLInputElement).value})}
function developer(){const allow=state.value.developer_access_enabled!==true;if(allow&&!confirm("Enable full agent developer access?"))return;send({type:"set_developer_access",allowed:allow})}
onMounted(()=>{connect();refresh=window.setInterval(()=>send({type:"refresh_state"}),1500)})
onBeforeUnmount(()=>{clearInterval(refresh);clearTimeout(reconnect);ws?.close()})
</script>
<template>
  <div class="space-y-5">
    <PageHeader title="Browser" description="Shared live control of the persistent Chromium profile.">
      <Tag :color="live ? 'green' : status === 'error' ? 'red' : 'default'">{{ status }}</Tag>
    </PageHeader>
    <div class="rounded-lg border border-border bg-muted px-4 py-2 text-sm">{{ message }}</div>
    <section class="rounded-xl border border-border bg-card shadow-sm">
      <div class="flex flex-wrap items-center gap-2 border-b border-border p-3">
        <Button variant="outline" size="sm" :disabled="!live" @click="send({type:'back'})">Back</Button>
        <Button variant="outline" size="sm" :disabled="!live" @click="send({type:'reload'})">Reload</Button>
        <Button variant="outline" size="sm" :disabled="!live" @click="send({type:'new_page'})">New tab</Button>
        <Button variant="outline" size="sm" :disabled="!live" @click="send({type:'close_page'})">Close</Button>
        <Button variant="outline" size="sm" :disabled="!live || state.can_reopen_closed_tab !== true" @click="send({type:'reopen_closed_page'})">Reopen</Button>
        <Button variant="outline" size="sm" :disabled="!live" @click="send({type:'new_page',url:'chrome://extensions/'})">Extensions</Button>
        <Button variant="outline" size="sm" :disabled="!live" @click="send({type:'open_docked_devtools',panel:'elements'})">DevTools</Button>
        <Button variant="outline" size="sm" :disabled="!live" @click="send({type:'open_devtools',panel:'elements'})">DevTools tab</Button>
        <Button variant="outline" size="sm" :disabled="!live" @click="send({type:'set_agent_access',allowed:state.agent_access_enabled===false})">Agents: {{ state.agent_access_enabled === false ? 'Blocked' : 'On' }}</Button>
        <Button variant="outline" size="sm" :disabled="!live" @click="developer">Developer: {{ state.developer_access_effective ? 'On' : state.developer_access_enabled ? 'Armed' : 'Off' }}</Button>
      </div>
      <form class="flex gap-2 border-b border-border p-3" @submit.prevent="send({type:'navigate',url})">
        <input v-model="url" class="field flex-1 font-mono text-xs" placeholder="https://example.com or chrome://extensions" />
        <Button size="sm" type="submit" :disabled="!live">Go</Button>
      </form>
      <div class="flex gap-2 overflow-x-auto border-b border-border p-2">
        <div v-for="page in pages" :key="page.page_id" class="min-w-60 max-w-72 cursor-pointer rounded-lg border p-2" :class="page.page_id === selectedId ? 'border-primary bg-accent' : 'border-border'" @click="send({type:'select_page',page_id:page.page_id})">
          <div class="flex gap-2"><input class="min-w-0 flex-1 bg-transparent text-xs font-semibold outline-none" :value="page.label || ''" :placeholder="page.title || 'Tab label'" @click.stop @change="setLabel(page,$event)" /><button class="rounded border px-1.5 text-[10px]" @click.stop="send({type:'set_page_agent_access',page_id:page.page_id,allowed:page.page_agent_access===false})">{{ page.page_agent_access === false ? 'Locked' : 'Agent' }}</button></div>
          <div class="mt-1 truncate text-xs">{{ page.title || '(untitled)' }}</div><div class="truncate text-[10px] text-muted-foreground">{{ page.url }}</div>
        </div>
        <div v-if="!pages.length" class="p-3 text-xs text-muted-foreground">No open tabs.</div>
      </div>
    </section>
    <div class="grid gap-3" :class="devId ? 'xl:grid-cols-[minmax(0,1fr)_minmax(360px,.72fr)]' : ''">
      <section class="overflow-hidden rounded-xl border border-border bg-card"><div class="flex justify-between border-b border-border p-3 text-sm font-medium"><span>Live browser</span><span class="text-xs text-muted-foreground">{{ dims.w }}×{{ dims.h }}</span></div><div class="browser-screen"><img ref="screen" tabindex="0" alt="Live Chromium tab" @mousedown="pointer(screen,selectedId,dims,$event,'mousePressed',button($event),1)" @mouseup="pointer(screen,selectedId,dims,$event,'mouseReleased',button($event),1)" @mousemove="e=>{const n=now();if(n-lastMove>33){lastMove=n;pointer(screen,selectedId,dims,e,'mouseMoved')}}" @wheel="wheel(screen,selectedId,dims,$event)" @keydown="key(selectedId,$event)" @contextmenu.prevent /></div></section>
      <section v-if="devId" class="overflow-hidden rounded-xl border border-border bg-card"><div class="flex justify-between border-b border-border p-3 text-sm font-medium"><span>DevTools</span><Button variant="ghost" size="sm" @click="send({type:'close_docked_devtools'})">Close</Button></div><div class="browser-screen"><img ref="devtools" tabindex="0" alt="Docked DevTools" @mousedown="pointer(devtools,devId,devDims,$event,'mousePressed',button($event),1)" @mouseup="pointer(devtools,devId,devDims,$event,'mouseReleased',button($event),1)" @mousemove="e=>{const n=now();if(n-devLastMove>33){devLastMove=n;pointer(devtools,devId,devDims,e,'mouseMoved')}}" @wheel="wheel(devtools,devId,devDims,$event)" @keydown="key(devId,$event)" @contextmenu.prevent /></div></section>
    </div>
  </div>
</template>
