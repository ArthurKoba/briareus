<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from "vue"
import { setLocale } from "@/shared/i18n"
import { useUiPreferences, type ThemePreference } from "@/shared/lib/preferences"
import { useI18n } from "vue-i18n"
import { checkControlPanelAccess, type ControlPanelAccessState } from "@/features/platform/api/control-panel-access"
import { clearTemporaryBearer, FirstUserError, registerFirstUser, signInFirstUser, signOutFirstUser, type VerifiedFirstUser } from "@/features/platform/api/temporary-first-user"
import RauthySignIn from "@/features/platform/ui/RauthySignIn.vue"

const { t } = useI18n()
const emit=defineEmits<{preview:[]}>()
const { locale, theme } = useUiPreferences()
function selectTheme(value: ThemePreference) { theme.value = value }
const state = ref<ControlPanelAccessState>("checking")
let controller: AbortController | null = null
let generation = 0
async function verifyApi() {
  controller?.abort()
  const current = new AbortController()
  controller = current
  const serial = ++generation
  state.value = "checking"
  const result = await checkControlPanelAccess(current.signal)
  if (!current.signal.aborted && serial === generation) {
    state.value = result
    controller = null
  }
}
const mode = ref<"login" | "register">("login")
const username = ref("")
const password = ref("")
const invitation = ref("")
const passwordVisible = ref(false)
const busy = ref(false)
let authController: AbortController | null = null
const confirmed = ref<VerifiedFirstUser | null>(null)
const notice = ref("")
const authError = ref("")
const labels = computed(() => locale.value === "ru" ? {
  login: "Войти по логину и паролю",
  register: "Регистрация по приглашению",
  username: "Логин",
  password: "Пароль",
  invitation: "Ключ приглашения",
  submitLogin: "Войти",
  submitRegister: "Создать учётную запись",
  signing: "Проверяем учётную запись…",
  showPassword: "Показать пароль",
  hidePassword: "Скрыть пароль",
  confirmed: "Личность подтверждена сервером",
  scopePending: "Вход выполнен через временный Identity API. Права на Projects, Teams и управление MCP пока не подтверждены Control Panel API.",
  logout: "Выйти",
  registered: "Учётная запись создана. Теперь войдите по логину и паролю.",
  logoutUncertain: "Токен удалён из браузера, но подтверждения отзыва на сервере нет.",
  unavailable: "Identity пока недоступен (503). Форма готова, но сервер не может выполнить вход. Требуется восстановить Identity или переключить BFF на Rauthy.",
  invalid: "Проверьте логин, пароль и данные формы.",
  denied: "Неверные данные входа или отсутствует разрешённый доступ.",
  invite: "Ключ приглашения недействителен или уже использован.",
  limited: "Слишком много попыток. Повторите позже.",
  network: "Не удалось получить ответ от сервера.",
  badResponse: "Сервер вернул неподтверждённый формат авторизации.",
  transitional: "Совместимость с прежним Identity API. Этот способ не подтверждает доступ к проектам и MCP.",
  legacyTitle: "Устаревший способ входа (переходный период)",
} : {
  login: "Sign in with username and password",
  register: "Register with invitation",
  username: "Username",
  password: "Password",
  invitation: "Invitation key",
  submitLogin: "Sign in",
  submitRegister: "Create account",
  signing: "Verifying account…",
  showPassword: "Show password",
  hidePassword: "Hide password",
  confirmed: "Identity verified by the server",
  scopePending: "Signed in through the temporary Identity API. Project, Team, and MCP management permissions are not yet verified by Control Panel API.",
  logout: "Sign out",
  registered: "Account created. Sign in with your username and password.",
  logoutUncertain: "Bearer cleared in browser; server revocation was not confirmed.",
  unavailable: "Identity is currently unavailable (503). The form is ready, but the server cannot complete sign-in. Restore Identity or cut BFF over to Rauthy.",
  invalid: "Check the username, password, and form fields.",
  denied: "Invalid credentials or access denied.",
  invite: "Invitation key is invalid or already used.",
  limited: "Too many attempts. Try again later.",
  network: "No response from server.",
  badResponse: "The server returned an unverified authentication format.",
  transitional: "Compatibility with the retired Identity API. This does not verify access to projects or MCP.",
  legacyTitle: "Legacy sign-in (transition only)",
})
function selectMode(value:"login"|"register"):void {
  mode.value=value
  authError.value=""
  notice.value=""
  password.value=""
  invitation.value=""
}
async function submitFirstUser():Promise<void> {
  if(busy.value || confirmed.value)return
  authError.value=""
  notice.value=""
  busy.value=true
  authController?.abort()
  const authRequest=new AbortController()
  authController=authRequest
  const secret=password.value
  try {
    if(mode.value==="register"){
      await registerFirstUser(invitation.value.trim(),username.value.trim(),secret,authRequest.signal)
      selectMode("login")
      notice.value=labels.value.registered
    }else{
      confirmed.value=await signInFirstUser(username.value.trim(),secret,authRequest.signal)
    }
  }catch(e){
    if(authRequest.signal.aborted)return
    const code=e instanceof FirstUserError?e.code:"BAD_RESPONSE"
    authError.value=code==="OWNER_SOURCE_UNAVAILABLE"?labels.value.unavailable:
      code==="INVITATION_REJECTED"?(mode.value==="register"?labels.value.invite:labels.value.denied):
      code==="AUTHENTICATION_RATE_LIMITED"?labels.value.limited:
      code==="AUTHENTICATION_REQUIRED"?labels.value.denied:
      code==="REQUEST_REJECTED"?labels.value.invalid:
      code==="NETWORK_ERROR"?labels.value.network:labels.value.badResponse
  }finally{
    password.value=""
    busy.value=false
    if(authController===authRequest)authController=null
  }
}
async function logoutFirstUser():Promise<void> {
  if(busy.value)return
  busy.value=true
  const revoked=await signOutFirstUser()
  confirmed.value=null
  busy.value=false
  if(!revoked)authError.value=labels.value.logoutUncertain
  void verifyApi()
}
onMounted(() => { void verifyApi() })
onBeforeUnmount(() => { ++generation; controller?.abort(); controller = null; authController?.abort(); authController=null; clearTemporaryBearer() })
</script>
<template>
  <section class="mx-auto grid w-full max-w-[1100px] overflow-hidden rounded-[28px] border border-border bg-card shadow-[0_32px_100px_-40px_rgba(8,35,55,.4)] lg:min-h-[600px] lg:grid-cols-[.9fr_1.1fr]" aria-labelledby="control-panel-login-title">
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
        <span class="inline-flex rounded-full border border-teal-200/25 bg-teal-200/10 px-3 py-1 text-[11px] font-semibold uppercase tracking-widest text-teal-100">{{ t('panelAccess.workspaceLabel') }}</span>
        <h2 class="mt-5 max-w-sm text-3xl font-semibold leading-tight tracking-tight sm:text-4xl">{{ t('panelAccess.heroTitle') }}</h2>
        <p class="mt-4 max-w-sm text-sm leading-7 text-slate-300">{{ t('panelAccess.heroDescription') }}</p>
      </div>
      <div class="relative z-10 mt-8 border-t border-white/15 pt-5 text-xs leading-6 text-slate-400">{{ t('panelAccess.permissionNotice') }}</div>
    </aside>
    <div class="flex min-w-0 flex-col justify-center px-5 py-9 sm:px-10 sm:py-12 lg:px-14">
      <div class="mb-7 flex flex-wrap items-center justify-end gap-3">
        <div class="inline-flex rounded-lg border border-border p-0.5" role="group" :aria-label="t('panelAccess.language')">
          <button type="button" class="min-h-10 min-w-11 rounded-md px-3 text-xs font-semibold transition focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-ring" :class="locale==='ru'?'bg-primary text-primary-foreground':'text-muted-foreground hover:bg-accent hover:text-foreground'" :aria-pressed="locale==='ru'" lang="ru" @click="setLocale('ru')">RU</button>
          <button type="button" class="min-h-10 min-w-11 rounded-md px-3 text-xs font-semibold transition focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-ring" :class="locale==='en'?'bg-primary text-primary-foreground':'text-muted-foreground hover:bg-accent hover:text-foreground'" :aria-pressed="locale==='en'" lang="en" @click="setLocale('en')">EN</button>
        </div>
        <div class="inline-flex max-w-full flex-wrap rounded-lg border border-border p-0.5" role="group" :aria-label="t('panelAccess.themeLabel')">
          <button type="button" class="min-h-10 rounded-md px-2.5 text-xs font-semibold transition focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-ring" :class="theme==='system'?'bg-primary text-primary-foreground':'text-muted-foreground hover:bg-accent hover:text-foreground'" :aria-pressed="theme==='system'" @click="selectTheme('system')">{{ t('panelAccess.themeSystem') }}</button>
          <button type="button" class="min-h-10 rounded-md px-2.5 text-xs font-semibold transition focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-ring" :class="theme==='light'?'bg-primary text-primary-foreground':'text-muted-foreground hover:bg-accent hover:text-foreground'" :aria-pressed="theme==='light'" @click="selectTheme('light')">{{ t('panelAccess.light') }}</button>
          <button type="button" class="min-h-10 rounded-md px-2.5 text-xs font-semibold transition focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-ring" :class="theme==='dark'?'bg-primary text-primary-foreground':'text-muted-foreground hover:bg-accent hover:text-foreground'" :aria-pressed="theme==='dark'" @click="selectTheme('dark')">{{ t('panelAccess.dark') }}</button>
        </div>
      </div>
      <div class="mb-8">
        <p class="mb-2 text-xs font-bold uppercase tracking-widest text-primary">{{ t('panelAccess.firstStep') }}</p>
        <h1 id="control-panel-login-title" class="text-2xl font-semibold tracking-tight text-foreground sm:text-3xl">{{ t('panelAccess.title') }}</h1>
        <p class="mt-3 text-sm leading-7 text-muted-foreground">{{ t('panelAccess.description') }}</p>
      </div>
      <div class="rounded-2xl border border-border bg-muted/40 p-5 sm:p-6" role="status" aria-live="polite" aria-atomic="true">
        <div class="mb-3 flex items-center gap-3">
          <span class="grid size-10 shrink-0 place-items-center rounded-xl bg-primary/10 text-lg font-bold text-primary" aria-hidden="true">B</span>
          <p class="text-sm font-semibold text-foreground">{{ t('panelAccess.connectionTitle') }}</p>
        </div>
        <p v-if="confirmed" class="text-sm leading-6 text-foreground">{{labels.confirmed}}</p>
        <p v-else-if="state==='checking'" class="text-sm leading-6 text-muted-foreground">{{ t('panelAccess.checking') }}</p>
        <p v-else-if="state==='signed_out'" class="text-sm leading-6 text-muted-foreground">{{ t('panelAccess.signedOut') }}</p>
        <p v-else-if="state==='denied'" class="text-sm leading-6 text-muted-foreground">{{ t('panelAccess.denied') }}</p>
        <p v-else-if="state==='unverified'" class="text-sm leading-6 text-muted-foreground">{{ t('panelAccess.unverified') }}</p>
        <p v-else class="text-sm leading-6 text-muted-foreground">{{ t('panelAccess.unavailable') }}</p>
      </div>
      <RauthySignIn />
      <!-- Legacy Identity stays as an explicit rollback-only disclosure until accepted OIDC cutover. -->
      <details class="mt-5 rounded-xl border border-border bg-muted/10 p-3 sm:p-4">
        <summary class="cursor-pointer text-sm font-medium text-muted-foreground focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-ring">{{labels.legacyTitle}}</summary>
        <div class="mt-4 space-y-4">
        <p class="text-xs leading-5 text-muted-foreground">{{labels.transitional}}</p>
        <div v-if="confirmed" class="space-y-3 rounded-xl border border-border bg-muted/30 p-4" role="status">
          <p class="text-sm font-semibold text-foreground">{{labels.confirmed}}</p>
          <p class="break-all font-mono text-xs text-muted-foreground">{{confirmed.user_id}}</p>
          <p class="text-sm text-muted-foreground">{{labels.scopePending}}</p>
          <button type="button" class="min-h-11 w-full rounded-lg border border-border px-4 text-sm font-semibold hover:bg-accent disabled:opacity-50" :disabled="busy" @click="logoutFirstUser">{{labels.logout}}</button>
        </div>
        <template v-else>
          <div class="grid grid-cols-2 gap-2" role="group" :aria-label="t('panelAccess.firstStep')">
            <button type="button" class="min-h-11 rounded-lg border border-border px-3 text-sm font-semibold" :class="mode==='login'?'bg-primary text-primary-foreground':'text-foreground hover:bg-accent'" :aria-pressed="mode==='login'" :disabled="busy" @click="selectMode('login')">{{labels.login}}</button>
            <button type="button" class="min-h-11 rounded-lg border border-border px-3 text-sm font-semibold" :class="mode==='register'?'bg-primary text-primary-foreground':'text-foreground hover:bg-accent'" :aria-pressed="mode==='register'" :disabled="busy" @click="selectMode('register')">{{labels.register}}</button>
          </div>
          <form class="space-y-3" @submit.prevent="submitFirstUser">
            <label v-if="mode==='register'" class="block text-sm font-semibold text-foreground">{{labels.invitation}}
              <input v-model="invitation" type="password" class="field mt-1.5" autocomplete="off" minlength="32" maxlength="256" required :disabled="busy" />
            </label>
            <label class="block text-sm font-semibold text-foreground">{{labels.username}}
              <input v-model="username" type="text" class="field mt-1.5" autocomplete="username" minlength="3" maxlength="128" required :disabled="busy" />
            </label>
            <label class="block text-sm font-semibold text-foreground">{{labels.password}}
              <span class="mt-1.5 flex min-w-0 gap-2">
                <input v-model="password" :type="passwordVisible?'text':'password'" class="field min-w-0 flex-1" :autocomplete="mode==='login'?'current-password':'new-password'" minlength="12" maxlength="4096" required :disabled="busy" />
                <button type="button" class="min-h-11 shrink-0 rounded-lg border border-border px-3 text-xs hover:bg-accent" :aria-label="passwordVisible?labels.hidePassword:labels.showPassword" :aria-pressed="passwordVisible" @click="passwordVisible=!passwordVisible">{{passwordVisible?labels.hidePassword:labels.showPassword}}</button>
              </span>
            </label>
            <p v-if="authError" role="alert" class="rounded-lg border border-destructive/30 bg-destructive/5 p-3 text-sm text-destructive">{{authError}}</p>
            <p v-if="notice" role="status" class="rounded-lg border border-border bg-muted/30 p-3 text-sm text-foreground">{{notice}}</p>
            <button type="submit" class="min-h-12 w-full rounded-xl bg-primary px-4 py-3 text-sm font-semibold text-primary-foreground disabled:opacity-50" :disabled="busy">{{busy?labels.signing:mode==='login'?labels.submitLogin:labels.submitRegister}}</button>
          </form>
        </template>
        </div>
      </details>
      <button type="button" class="mt-4 w-full rounded-xl border border-border px-4 py-3 text-sm font-medium transition hover:bg-accent focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-ring disabled:opacity-50" :disabled="state==='checking'" @click="verifyApi">{{ t('panelAccess.retry') }}</button>
      <button type="button" class="mt-4 w-full rounded-xl border border-primary/30 bg-primary/5 px-4 py-3 text-sm font-semibold text-primary transition hover:bg-primary/10 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-ring" @click="emit('preview')">{{t('panelAccess.exploreModules')}}</button>
      <p class="mt-2 text-xs leading-6 text-muted-foreground">{{t('panelAccess.previewNotice')}}</p>
      <p class="mt-4 text-xs leading-6 text-muted-foreground">{{ t('panelAccess.accountServices') }}</p>
      <div class="mt-8 border-t border-border pt-5 text-center text-sm text-muted-foreground">
        <a href="/" class="inline-flex min-h-10 items-center gap-2 rounded-lg px-2 text-primary underline-offset-4 hover:underline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-ring">← {{ t('app.publicWebsite') }}</a>
      </div>
    </div>
  </section>
</template>
