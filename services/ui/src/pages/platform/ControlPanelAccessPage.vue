<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from "vue"
import { useI18n } from "vue-i18n"
import { KeyRound, LoaderCircle, LockKeyhole } from "lucide-vue-next"
import type { RauthyPanelState } from "@/features/platform/api/rauthy-oidc"
import { prepareNativeRauthyLogin } from "@/features/platform/api/native-rauthy"
import {checkNativePrelogin,cancelNativePrelogin} from "@/features/platform/api/native-prelogin-control"
import RauthySignIn from "@/features/platform/ui/RauthySignIn.vue"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/shared/ui/card"
import { Input } from "@/shared/ui/input"
import { Button } from "@/shared/ui/button"
import { Separator } from "@/shared/ui/separator"

/** Native Init and explicit cancel are safe, cookie-bound prelogin steps.
 * The credential/PoW/MFA UI is disabled until its owner protocol can be
 * connected and independently accepted. Neither Init nor capabilities grants access.
 */
const props=withDefaults(defineProps<{
  designPreview?:boolean
  initialSession?:RauthyPanelState|null
  managedLogout?:boolean
}>(),{designPreview:false})
const emit=defineEmits<{
  providerState:[value:RauthyPanelState|{kind:"checking"}]
  logoutRequested:[]
}>()
const {locale}=useI18n()
const status=ref<RauthyPanelState|{kind:"checking"}>(
  props.designPreview?{kind:"signed_out"}:props.initialSession??{kind:"checking"},
)
const checking=computed(()=>status.value.kind==="checking")
const native=ref<"idle"|"checking"|"prepared"|"canceling"|"cancelled"|"forbidden"|"unavailable"|"invalid"|"expired">("idle")
const nativeCode=ref("")
const nativeUntil=ref<number|null>(null)
let nativeExpiry:ReturnType<typeof setTimeout>|null=null
let nativeMonotonicUntil:number|null=null
let nativeController:AbortController|null=null
const secureNativeOrigin=window.location.protocol==="https:"&&window.isSecureContext
function expireNative():void{
  if(native.value!=="prepared"||nativeUntil.value===null||nativeMonotonicUntil===null)return
  if(nativeExpiry!==null){clearTimeout(nativeExpiry);nativeExpiry=null}
  const remaining=Math.min(nativeUntil.value-Date.now(),nativeMonotonicUntil-performance.now())
  if(remaining>0){nativeExpiry=setTimeout(expireNative,Math.ceil(remaining));return}
  native.value="expired";nativeCode.value="NATIVE_PREPARATION_EXPIRED";nativeUntil.value=null;nativeMonotonicUntil=null
}
function resetNative():void{
  nativeController?.abort();nativeController=null
  if(nativeExpiry!==null){clearTimeout(nativeExpiry);nativeExpiry=null}
  nativeUntil.value=null;nativeMonotonicUntil=null;native.value="idle";nativeCode.value=""
}
function onVisible():void{if(document.visibilityState==="visible")expireNative()}
onMounted(()=>document.addEventListener("visibilitychange",onVisible))

async function prepareNative():Promise<void>{
  if(props.designPreview||!secureNativeOrigin||
    native.value==="checking"||native.value==="prepared"||
    status.value.kind==="signed_in")return
  nativeController?.abort()
  const request=new AbortController()
  nativeController=request
  native.value="checking"
  nativeCode.value=""
  nativeUntil.value=null
  if(nativeExpiry!==null){clearTimeout(nativeExpiry);nativeExpiry=null}
  const deadline=setTimeout(()=>request.abort(),9000)
  try{
    const protocol=await checkNativePrelogin(request.signal)
    if(nativeController!==request)return
    if(protocol.kind!=="supported"){
      native.value=protocol.kind==="invalid"?"invalid":protocol.kind==="forbidden"?"forbidden":"unavailable"
      nativeCode.value=protocol.code
      return
    }
    const result=await prepareNativeRauthyLogin(request.signal)
    if(nativeController!==request)return
    if(request.signal.aborted){native.value="unavailable";nativeCode.value="NATIVE_PREPARATION_CANCELLED";return}
    native.value=result.kind
    if(result.kind==="prepared"){
      nativeUntil.value=result.expiresAt
      nativeMonotonicUntil=performance.now()+Math.max(0,result.expiresAt-Date.now())
      expireNative()
    }else nativeCode.value=result.code
  }finally{
    clearTimeout(deadline)
    if(nativeController===request)nativeController=null
  }
}

async function cancelPreparedNative():Promise<void>{
  if(native.value!=="prepared"||status.value.kind==="signed_in")return
  const request=new AbortController()
  nativeController?.abort()
  nativeController=request
  native.value="canceling"
  nativeCode.value=""
  const deadline=setTimeout(()=>request.abort(),8500)
  try{
    const result=await cancelNativePrelogin(request.signal)
    if(nativeController!==request)return
    if(result.kind==="cancelled"){
      resetNative()
      native.value="cancelled"
      return
    }
    // A disconnected reply is not evidence that server cleanup succeeded.
    native.value=result.kind==="forbidden"?"forbidden":"unavailable"
    nativeCode.value=result.code
    nativeUntil.value=null;nativeMonotonicUntil=null
    if(nativeExpiry!==null){clearTimeout(nativeExpiry);nativeExpiry=null}
  }finally{
    clearTimeout(deadline)
    if(nativeController===request)nativeController=null
  }
}

const labels=computed(()=>locale.value==="ru"?{
  title:"Вход в Control Panel",
  description:"Используйте существующую учётную запись Briareus. Управление проектами и инструментами доступно только после подтверждения прав.",
  username:"Логин или почта",
  password:"Пароль",
  show:"Показать пароль",
  hide:"Скрыть пароль",
  submit:"Войти",
  coming:"Вход по паролю пока недоступен. Учётные данные здесь не вводятся и не отправляются.",
  pending:"Проверка сервиса…",
  online:"Сервис авторизации отвечает",
  signedOut:"Не авторизованы",
  identified:"Сеанс Rauthy подтверждён; права Briareus проверяются отдельно",
  offline:"Авторизация временно недоступна",
  provider:"Подтверждение сеанса",
  providerNote:"Control Panel использует Rauthy через собственный Backend API. Внешний интерфейс входа не открывается.",
  embedded:"Вход по логину и паролю",
  prepare:"Подготовить вход",
  preparing:"Подготавливаем защищённую сессию входа…",
  prepared:"Сессия входа подготовлена. Ввод пароля будет доступен после подключения Rauthy к форме входа.",
  cancel:"Отменить подготовку",canceling:"Отменяем одноразовую транзакцию…",cancelled:"Подготовка входа отменена сервером.",
  nativeUnavailable:"Подготовка входа недоступна. Учётные данные не отправлялись.",
  nativeExpired:"Срок подготовки входа истёк. Для следующей попытки создайте новую транзакцию.",
  nativeUntil:"Подготовка действует до",
  nativeInvalid:"Некорректный ответ сервера при подготовке входа. Дальнейшие действия заблокированы.",
  nativeForbidden:"Сервер отклонил подготовку входа. Проверьте адрес и HTTPS.",
  nativeHttps:"Подготовка входа доступна только через защищённый HTTPS-адрес.",
}:{
  title:"Control Panel sign-in",
  description:"Use your existing Briareus account. Projects and tools require verified access rights.",
  username:"Username or email",
  password:"Password",
  show:"Show password",
  hide:"Hide password",
  submit:"Sign in",
  coming:"Password sign-in is not yet available. This screen does not collect or submit credentials.",
  pending:"Checking service…",
  online:"Identity service reachable",
  signedOut:"Not authenticated",
  identified:"Rauthy session verified; Briareus permissions are checked separately",
  offline:"Identity service unavailable",
  provider:"Session verification",
  providerNote:"Control Panel uses Rauthy through its own Backend API, without opening an external sign-in interface.",
  embedded:"Username and password sign-in",
  prepare:"Prepare sign-in",
  preparing:"Preparing a secure sign-in session…",
  prepared:"Sign-in session prepared. Password entry will be available when Rauthy is connected to this form.",
  nativeUnavailable:"Sign-in preparation is unavailable. No credentials were sent.",
  nativeExpired:"Sign-in preparation expired. Start a new transaction for the next attempt.",
  nativeUntil:"Preparation valid until",
  nativeInvalid:"Invalid server response while preparing sign-in. Further actions remain blocked.",
  nativeForbidden:"Server rejected sign-in preparation. Check the address and HTTPS.",
  nativeHttps:"Sign-in preparation requires a secure HTTPS address.",
})
const connection=computed(()=>{
  if(checking.value)return labels.value.pending
  if(status.value.kind==="signed_in")return labels.value.identified
  if(status.value.kind==="signed_out")return labels.value.signedOut
  return labels.value.offline
})
// RauthySignIn owns the identity request once. The sidebar status below
// follows that existing component instead of launching another /session
// and /config request per login screen render. Verified Platform /me
// remains separately owned by OidcPanelPage.
function onProviderState(value:RauthyPanelState|{kind:"checking"}):void {
  if(value.kind==="signed_in"||status.value.kind==="signed_in")resetNative()
  status.value=value
  emit("providerState",value)
}
onBeforeUnmount(()=>{resetNative();document.removeEventListener("visibilitychange",onVisible)})
</script>

<template>
  <section class="mx-auto grid w-full max-w-[1060px] gap-6 pt-2 lg:grid-cols-[minmax(0,1.05fr)_minmax(260px,.8fr)] lg:gap-8 lg:pt-10" aria-label="Control Panel sign in">
    <Card class="min-w-0 rounded-2xl">
      <CardHeader class="space-y-3 pb-5">
        <span class="flex size-11 items-center justify-center rounded-xl border border-border bg-muted/40"><LockKeyhole class="size-5 text-foreground" /></span>
        <CardTitle class="text-2xl tracking-tight">{{labels.title}}</CardTitle>
        <CardDescription class="max-w-lg text-sm leading-6">{{labels.description}}</CardDescription>
      </CardHeader>
      <CardContent class="space-y-5">
        <section v-if="!designPreview" aria-label="Rauthy authentication" class="space-y-2">
          <h2 class="text-sm font-semibold">{{labels.provider}}</h2>
          <p class="text-xs leading-5 text-muted-foreground">{{labels.providerNote}}</p>
          <RauthySignIn :initial-state="initialSession" :managed-logout="managedLogout" @logout-requested="emit('logoutRequested')" @state="onProviderState"/>
        </section>
        <Separator v-if="!designPreview"/>
        <h2 class="text-sm font-semibold text-foreground">{{labels.embedded}}</h2>
        <div v-if="!designPreview" class="space-y-2">
          <Button type="button" variant="outline" class="w-full"
            :disabled="!secureNativeOrigin||checking||native==='checking'||native==='prepared'||native==='canceling'||status.kind==='signed_in'"
            @click="prepareNative">
            <LoaderCircle v-if="native==='checking'" class="mr-2 size-4 animate-spin"/>
            {{native==='checking'?labels.preparing:labels.prepare}}
          </Button>
          <p role="status" class="text-xs leading-5 text-muted-foreground">
            {{!secureNativeOrigin?labels.nativeHttps:
              native==='prepared'?labels.prepared:
              native==='canceling'?labels.canceling:
              native==='cancelled'?labels.cancelled:
              native==='checking'?labels.preparing:
              native==='expired'?labels.nativeExpired:
              native==='invalid'?labels.nativeInvalid:
              native==='forbidden'?labels.nativeForbidden:
              native==='unavailable'?labels.nativeUnavailable:labels.coming}}
          </p>
          <p v-if="native==='prepared'&&nativeUntil" class="text-xs text-muted-foreground">{{labels.nativeUntil}}: {{new Date(nativeUntil).toLocaleTimeString(locale)}}</p>
          <Button v-if="native==='prepared'" type="button" variant="outline" size="sm"
            :disabled="checking" @click="cancelPreparedNative">{{labels.cancel}}</Button>
          <code v-if="nativeCode" class="block text-xs text-muted-foreground">{{nativeCode}}</code>
        </div>
        <form class="space-y-4" autocomplete="off" @submit.prevent>
          <label class="block space-y-2 text-sm font-medium">
            <span>{{labels.username}}</span>
            <Input autocomplete="off" type="text" :placeholder="labels.username" :disabled="true" readonly />
          </label>
          <label class="block space-y-2 text-sm font-medium">
            <span>{{labels.password}}</span>
            <span class="flex gap-2">
              <Input type="password" autocomplete="off" :placeholder="labels.password" :disabled="true" readonly />
            </span>
          </label>
          <Button type="submit" class="w-full" size="lg" :disabled="true">
            <KeyRound class="mr-2 size-4" />{{labels.submit}}
          </Button>
        </form>
        <p class="min-h-12 rounded-lg border border-border bg-muted/30 px-3 py-3 text-xs leading-5 text-muted-foreground" role="status">{{labels.coming}}</p>
      </CardContent>
    </Card>
    <aside class="min-w-0 self-start rounded-xl border border-border bg-card/60 p-4 lg:mt-4 lg:p-6" aria-live="polite">
      <p class="mb-4 text-xs font-semibold uppercase tracking-[.12em] text-muted-foreground">Briareus · Identity</p>
      <div class="flex min-h-14 items-center gap-3">
        <LoaderCircle v-if="checking" class="size-5 shrink-0 animate-spin text-primary" aria-hidden="true" />
        <span v-else class="size-2.5 shrink-0 rounded-full" :class="status.kind==='unavailable'?'bg-destructive':'bg-primary'" aria-hidden="true" />
        <p class="text-sm font-medium">{{connection}}</p>
      </div>
      <p class="mt-3 text-xs leading-6 text-muted-foreground">{{labels.description}}</p>
    </aside>
  </section>
</template>
