<script setup lang="ts">
import { onBeforeUnmount, reactive, ref } from "vue"
import { useI18n } from "vue-i18n"
import { createFirstUserClient, FirstUserWireError, type FirstUserError, type VerifiedFirstUser } from "@/features/platform/api/first-user-client"

const {t}=useI18n()
const client=createFirstUserClient()
const mode=ref<"login"|"register">("login")
const input=reactive({username:"",password:"",confirm:"",invitation:""})
const current=ref<VerifiedFirstUser|null>(null)
const busy=ref(false)
const error=ref<FirstUserError|null>(null)
const registered=ref(false)
const uncertain=ref(false)
const passwordVisible=ref(false)
const confirmationVisible=ref(false)
const invitationVisible=ref(false)
let controller:AbortController|null=null
let generation=0
let expiryTimer:ReturnType<typeof setTimeout>|null=null
function clearExpiryTimer(){if(expiryTimer!==null){clearTimeout(expiryTimer);expiryTimer=null}}
function expireLocally(){
  clearExpiryTimer()
  client.invalidate()
  current.value=null
  error.value="unauthorized"
}
function scheduleExpiry(){
  clearExpiryTimer()
  const delay=client.expiresAt()-Date.now()
  if(delay<=0){expireLocally();return}
  expiryTimer=setTimeout(expireLocally,delay)
}
function resetCredentials(){
  input.password="";input.confirm="";input.invitation=""
  passwordVisible.value=false;confirmationVisible.value=false;invitationVisible.value=false
}
function changeMode(next:"login"|"register"){
  // An uncertain registration may navigate to login, but NEVER resubmit the code.
  if(busy.value||(uncertain.value&&next!=="login"))return
  resetCredentials()
  uncertain.value=false
  error.value=null
  registered.value=false
  mode.value=next
}
function classify(cause:unknown):FirstUserError{
  return cause instanceof FirstUserWireError?cause.kind:"unavailable"
}
async function submit(){
  if(busy.value||uncertain.value||current.value)return
  if(input.username.trim().length<3||input.username.trim().length>128||
     input.password.length<12||input.password.length>4096)return
  const registering=mode.value==="register"
  if(registering&&(input.password!==input.confirm||
     !/^[A-Za-z0-9_-]{32,256}$/.test(input.invitation)))return
  busy.value=true;error.value=null;registered.value=false
  const signal=(controller=new AbortController()).signal
  const operation=++generation
  try{
    if(registering){
      await client.register(input.invitation,input.username.trim(),input.password,signal)
      if(operation!==generation||signal.aborted)return
      registered.value=true
      mode.value="login"
    }else{
      const user=await client.login(input.username.trim(),input.password,signal)
      if(operation!==generation||signal.aborted)return
      current.value=user
      scheduleExpiry()
    }
  }catch(cause){
    if(operation!==generation||signal.aborted)return
    error.value=classify(cause)
    if(registering)uncertain.value=error.value!=="invalid"
  }finally{
    resetCredentials()
    if(operation===generation){busy.value=false;controller=null}
  }
}
async function refresh(){
  if(busy.value||!current.value)return
  busy.value=true;error.value=null
  const signal=(controller=new AbortController()).signal
  const operation=++generation
  try{
    const user=await client.current(signal)
    if(operation!==generation||signal.aborted)return
    current.value=user
    scheduleExpiry()
  }catch(cause){
    if(operation!==generation||signal.aborted)return
    clearExpiryTimer()
    // A stale verification does not keep a displayed current User.
    current.value=null
    client.invalidate()
    error.value=classify(cause)
  }finally{if(operation===generation){busy.value=false;controller=null}}
}
async function logout(){
  if(busy.value)return
  busy.value=true;error.value=null
  const signal=(controller=new AbortController()).signal
  const operation=++generation
  // Clear displayed access synchronously, before the remote revocation.
  current.value=null
  clearExpiryTimer()
  const confirmed=await client.logout(signal)
  if(operation===generation){
    if(!confirmed)error.value="uncertain"
    busy.value=false;controller=null
  }
}
onBeforeUnmount(()=>{
  clearExpiryTimer()
  ++generation
  controller?.abort();controller=null
  client.invalidate();resetCredentials()
  input.username=""
  current.value=null
})
</script>
<template>
  <section class="mx-auto grid w-full max-w-[1100px] overflow-hidden rounded-[28px] border border-border bg-card shadow-[0_32px_100px_-40px_rgba(8,35,55,.4)] lg:min-h-[600px] lg:grid-cols-[.9fr_1.1fr]" aria-labelledby="first-user-title">
    <aside class="relative isolate overflow-hidden bg-[#101f31] px-6 py-9 text-slate-100 sm:px-10 lg:flex lg:flex-col lg:justify-between lg:px-12 lg:py-12">
      <div class="pointer-events-none absolute -right-32 -top-36 -z-10 size-[420px] rounded-full bg-teal-400/20 blur-[95px]" aria-hidden="true" />
      <div class="pointer-events-none absolute -bottom-40 -left-24 -z-10 size-[390px] rounded-full bg-sky-500/20 blur-[95px]" aria-hidden="true" />
      <div class="relative z-10 flex items-center gap-3">
        <span class="grid size-11 shrink-0 place-items-center rounded-xl border border-teal-300/30 bg-teal-300/10 text-lg font-black text-teal-200" aria-hidden="true">B</span>
        <div>
          <p class="text-[11px] font-bold uppercase tracking-[.18em] text-teal-200/80">Briareus</p>
          <p class="text-base font-semibold leading-6">Control Panel</p>
        </div>
      </div>
      <div class="relative z-10 mt-12 lg:my-12">
        <span class="inline-flex rounded-full border border-teal-200/25 bg-teal-200/10 px-3 py-1 text-[11px] font-semibold uppercase tracking-widest text-teal-100">{{t('firstUser.workspaceLabel')}}</span>
        <h2 class="mt-5 max-w-sm text-3xl font-semibold leading-tight tracking-tight sm:text-4xl">{{t('firstUser.heroTitle')}}</h2>
        <p class="mt-4 max-w-sm text-sm leading-7 text-slate-300">{{t('firstUser.heroDescription')}}</p>
      </div>
      <div class="relative z-10 mt-8 border-t border-white/15 pt-5 text-xs leading-6 text-slate-400">
        {{t('firstUser.scopeNotice')}}
      </div>
    </aside>
    <div class="flex min-w-0 flex-col justify-center px-5 py-9 sm:px-10 sm:py-12 lg:px-14">
      <div class="mb-7">
        <p class="mb-2 text-xs font-bold uppercase tracking-widest text-primary">{{t('firstUser.firstStep')}}</p>
        <h1 id="first-user-title" class="text-2xl font-semibold tracking-tight text-foreground sm:text-3xl">{{current?t('firstUser.verified'):(mode==='register'?t('firstUser.register'):t('app.signIn'))}}</h1>
        <p class="mt-3 text-sm leading-6 text-muted-foreground">{{t('firstUser.boundary')}}</p>
      </div>
      <div v-if="current" role="status" class="space-y-5">
        <dl class="space-y-4 rounded-xl border border-border bg-muted/30 p-5 text-sm">
          <div><dt class="text-xs text-muted-foreground">{{t('firstUser.userId')}}</dt><dd class="mt-1 break-all font-mono font-medium">{{current.userId}}</dd></div>
          <div><dt class="text-xs text-muted-foreground">{{t('firstUser.credentialVersion')}}</dt><dd class="mt-1 font-semibold">{{current.credentialVersion}}</dd></div>
        </dl>
        <p class="text-sm leading-6 text-muted-foreground">{{t('firstUser.scopeNotice')}}</p>
        <button type="button" class="w-full rounded-xl border border-border px-4 py-3 text-sm font-medium transition hover:bg-accent focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-ring disabled:opacity-50" :disabled="busy" @click="refresh">{{t('firstUser.verifyAgain')}}</button>
        <button type="button" class="w-full rounded-xl bg-primary px-4 py-3 text-sm font-semibold text-primary-foreground transition hover:opacity-90 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-ring disabled:opacity-50" :disabled="busy" @click="logout">{{t('app.signOut')}}</button>
      </div>
      <template v-else>
        <p v-if="registered" class="mb-5 rounded-xl border border-teal-400/30 bg-teal-400/10 p-4 text-sm leading-6" role="status">{{t('firstUser.registered')}}</p>
        <div class="mb-6 grid grid-cols-2 gap-1 rounded-xl bg-muted/60 p-1" role="group" :aria-label="t('firstUser.authMethod')">
          <button type="button" class="min-h-11 rounded-lg px-3 py-2 text-sm font-semibold transition focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-ring" :class="mode==='login'?'bg-card text-foreground shadow-sm':'text-muted-foreground hover:text-foreground'" :aria-pressed="mode==='login'" :disabled="busy" @click="changeMode('login')">{{t('app.signIn')}}</button>
          <button type="button" class="min-h-11 rounded-lg px-3 py-2 text-sm font-semibold transition focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-ring disabled:opacity-50" :class="mode==='register'?'bg-card text-foreground shadow-sm':'text-muted-foreground hover:text-foreground'" :aria-pressed="mode==='register'" :disabled="busy||uncertain" @click="changeMode('register')">{{t('firstUser.register')}}</button>
        </div>
        <form v-if="!uncertain" class="space-y-4" @submit.prevent="submit">
          <div v-if="mode==='register'" class="space-y-1.5">
            <label for="first-user-invitation" class="block text-sm font-medium">{{t('firstUser.invitation')}}</label>
            <div class="relative">
              <input id="first-user-invitation" v-model="input.invitation" class="field secret-field min-h-12" :type="invitationVisible?'text':'password'" autocomplete="off" autocapitalize="off" autocorrect="off" spellcheck="false" minlength="32" maxlength="256" :disabled="busy" required />
              <button type="button" class="absolute inset-y-0 right-2 my-1 rounded-md px-3 text-xs font-semibold text-muted-foreground hover:text-foreground focus-visible:outline-2 focus-visible:outline-ring" :aria-label="invitationVisible?t('firstUser.hideSecret'):t('firstUser.showSecret')" :aria-pressed="invitationVisible" @click="invitationVisible=!invitationVisible">{{invitationVisible?t('firstUser.hide'):t('firstUser.show')}}</button>
            </div>
            <p class="text-xs leading-5 text-muted-foreground">{{t('firstUser.invitationHint')}}</p>
          </div>
          <div class="space-y-1.5">
            <label for="first-user-username" class="block text-sm font-medium">{{t('app.username')}}</label>
            <input id="first-user-username" v-model="input.username" class="field min-h-12" autocomplete="username" minlength="3" maxlength="128" :disabled="busy" required />
          </div>
          <div class="space-y-1.5">
            <label for="first-user-password" class="block text-sm font-medium">{{t('app.password')}}</label>
            <div class="relative">
              <input id="first-user-password" v-model="input.password" class="field secret-field min-h-12" :type="passwordVisible?'text':'password'" :autocomplete="mode==='register'?'new-password':'current-password'" minlength="12" maxlength="4096" :disabled="busy" required />
              <button type="button" class="absolute inset-y-0 right-2 my-1 rounded-md px-3 text-xs font-semibold text-muted-foreground hover:text-foreground focus-visible:outline-2 focus-visible:outline-ring" :aria-label="passwordVisible?t('firstUser.hideSecret'):t('firstUser.showSecret')" :aria-pressed="passwordVisible" @click="passwordVisible=!passwordVisible">{{passwordVisible?t('firstUser.hide'):t('firstUser.show')}}</button>
            </div>
          </div>
          <div v-if="mode==='register'" class="space-y-1.5">
            <label for="first-user-confirm" class="block text-sm font-medium">{{t('firstUser.confirm')}}</label>
            <div class="relative">
              <input id="first-user-confirm" v-model="input.confirm" class="field secret-field min-h-12" :type="confirmationVisible?'text':'password'" autocomplete="new-password" minlength="12" maxlength="4096" :disabled="busy" required />
              <button type="button" class="absolute inset-y-0 right-2 my-1 rounded-md px-3 text-xs font-semibold text-muted-foreground hover:text-foreground focus-visible:outline-2 focus-visible:outline-ring" :aria-label="confirmationVisible?t('firstUser.hideSecret'):t('firstUser.showSecret')" :aria-pressed="confirmationVisible" @click="confirmationVisible=!confirmationVisible">{{confirmationVisible?t('firstUser.hide'):t('firstUser.show')}}</button>
            </div>
            <p v-if="input.confirm&&input.confirm!==input.password" class="text-xs text-destructive" role="status">{{t('firstUser.passwordMismatch')}}</p>
          </div>
          <button type="submit" class="mt-2 flex min-h-12 w-full items-center justify-center rounded-xl bg-primary px-4 py-3 text-sm font-semibold text-primary-foreground transition hover:opacity-90 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-ring disabled:cursor-not-allowed disabled:opacity-50" :disabled="busy||mode==='register'&&input.password!==input.confirm">{{busy?t('firstUser.working'):(mode==='register'?t('firstUser.register'):t('app.signIn'))}} <span v-if="!busy" class="ml-2" aria-hidden="true">→</span></button>
        </form>
      </template>
      <div v-if="error" class="mt-5 rounded-xl border border-destructive/30 bg-destructive/5 p-4 text-sm leading-6 text-destructive" role="alert" aria-live="assertive">{{t(`firstUser.errors.${error}`)}}</div>
      <p v-if="uncertain" class="mt-3 text-sm leading-6 text-muted-foreground">{{t('firstUser.noRetry')}}</p>
      <div class="mt-8 border-t border-border pt-5 text-center text-sm text-muted-foreground">
        <a href="/" class="inline-flex min-h-10 items-center gap-2 rounded-lg px-2 text-primary underline-offset-4 hover:underline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-ring">← {{t('app.publicWebsite')}}</a>
      </div>
    </div>
  </section>
</template>
