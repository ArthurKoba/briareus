<script setup lang="ts">
import {defineAsyncComponent} from "vue"
import {useI18n} from "vue-i18n"
import ToastHost from "@/shared/notifications/ToastHost.vue"
import ControlPanelChunkFailure from "@/app/ControlPanelChunkFailure.vue"

/** The ONLY production entry is the server-owned Rauthy session + current
 * Platform User/Project proof. The deprecated PlatformPort cannot be
 * installed and must not leave a competing guest/Identity/legacy UI path.
 *
 * LocalDesignPreview is DEV-only; no query parameter, localStorage item or
 * browser signal can turn it on in the production application bundle.
 */
// The full Panel workspace is not necessary to paint the login bootstrap.
// Keep the first production chunk small while still preserving exactly ONE
// server-authoritative Rauthy -> current Platform owner root.
// A staggered Dev UI release can temporarily remove the lazy auth chunk.
// Resolve to a LOCAL, read-only reload screen, never guest content or a
// retry of an authentication/approval POST.
const OidcPanelPage=defineAsyncComponent(()=>
  import("@/pages/platform/OidcPanelPage.vue").catch(()=>ControlPanelChunkFailure)
)
const {t}=useI18n()
const LocalDesignPreview=import.meta.env.DEV
  ? defineAsyncComponent(()=>import("@/pages/preview/LocalDesignPreview.vue"))
  : null
const localDesignPreview=import.meta.env.DEV&&
  new URLSearchParams(window.location.search).get("ui-preview")==="1"
</script>

<template>
  <ToastHost/>
  <LocalDesignPreview v-if="localDesignPreview"/>
  <Suspense v-else>
    <OidcPanelPage/>
    <template #fallback>
      <main class="flex min-h-screen items-center justify-center bg-background p-6" role="status" aria-live="polite">
        <p class="text-sm text-muted-foreground">{{t("app.loading")}}</p>
      </main>
    </template>
  </Suspense>
</template>
