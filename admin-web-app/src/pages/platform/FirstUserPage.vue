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
function resetCredentials(){input.password="";input.confirm="";input.invitation=""}
function changeMode(next:"login"|"register"){
  if(busy.value||uncertain.value)return
  resetCredentials()
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
  <section class="w-full max-w-md rounded-xl border border-border bg-card p-6 shadow-sm" aria-labelledby="first-user-title">
    <h1 id="first-user-title" class="text-xl font-semibold">{{t('app.title')}}</h1>
    <p class="mt-2 text-sm text-muted-foreground">{{t('firstUser.boundary')}}</p>
    <div v-if="current" role="status" class="mt-6 space-y-4">
      <h2 class="font-semibold">{{t('firstUser.verified')}}</h2>
      <dl class="break-all rounded-lg bg-muted/30 p-4 text-sm">
        <dt class="text-muted-foreground">{{t('firstUser.userId')}}</dt>
        <dd class="mb-3 font-mono">{{current.userId}}</dd>
        <dt class="text-muted-foreground">{{t('firstUser.credentialVersion')}}</dt>
        <dd>{{current.credentialVersion}}</dd>
      </dl>
      <p class="text-sm text-muted-foreground">{{t('firstUser.scopeNotice')}}</p>
      <button type="button" class="w-full rounded-md border border-border p-2 text-sm" :disabled="busy" @click="refresh">{{t('firstUser.verifyAgain')}}</button>
      <button type="button" class="w-full rounded-md bg-primary p-2 text-sm text-primary-foreground" :disabled="busy" @click="logout">{{t('app.signOut')}}</button>
    </div>
    <template v-else>
      <p v-if="registered" class="mt-4 text-sm" role="status">{{t('firstUser.registered')}}</p>
      <div class="mt-5 flex gap-3 text-sm" aria-label="Authentication">
        <button type="button" class="rounded-md px-3 py-2" :class="mode==='login'?'bg-accent font-semibold':'text-muted-foreground'" :disabled="busy||uncertain" @click="changeMode('login')">{{t('app.signIn')}}</button>
        <button type="button" class="rounded-md px-3 py-2" :class="mode==='register'?'bg-accent font-semibold':'text-muted-foreground'" :disabled="busy||uncertain" @click="changeMode('register')">{{t('firstUser.register')}}</button>
      </div>
      <form v-if="!uncertain" class="mt-4 space-y-4" @submit.prevent="submit">
        <label v-if="mode==='register'" class="block space-y-1.5 text-sm"><span>{{t('firstUser.invitation')}}</span><input v-model="input.invitation" class="field" type="password" autocomplete="off" autocapitalize="off" autocorrect="off" spellcheck="false" minlength="32" maxlength="256" required /></label>
        <label class="block space-y-1.5 text-sm"><span>{{t('app.username')}}</span><input v-model="input.username" class="field" autocomplete="username" minlength="3" maxlength="128" required /></label>
        <label class="block space-y-1.5 text-sm"><span>{{t('app.password')}}</span><input v-model="input.password" class="field" type="password" :autocomplete="mode==='register'?'new-password':'current-password'" minlength="12" maxlength="4096" required /></label>
        <label v-if="mode==='register'" class="block space-y-1.5 text-sm"><span>{{t('firstUser.confirm')}}</span><input v-model="input.confirm" class="field" type="password" autocomplete="new-password" minlength="12" maxlength="4096" required /></label>
        <button type="submit" class="w-full rounded-md bg-primary p-3 text-sm font-semibold text-primary-foreground disabled:opacity-50" :disabled="busy">{{busy?t('app.loading'):(mode==='register'?t('firstUser.register'):t('app.signIn'))}}</button>
      </form>
    </template>
    <p v-if="error" class="mt-4 text-sm text-destructive" role="alert">{{t(`firstUser.errors.${error}`)}}</p>
    <p v-if="uncertain" class="mt-3 text-xs text-muted-foreground">{{t('firstUser.noRetry')}}</p>
    <p class="mt-6 text-center"><a href="/" class="text-sm text-primary underline underline-offset-4">{{t('app.publicWebsite')}}</a></p>
  </section>
</template>
