<script setup lang="ts">
import {useI18n} from "vue-i18n"
import {Button} from "@/shared/ui/button"

const {t}=useI18n()
function retry():void{window.location.reload()}
</script>
<template>
  <main class="flex min-h-screen items-center justify-center bg-background px-4 py-10" role="alert">
    <section class="w-full max-w-md space-y-4 rounded-xl border border-border bg-card p-6 text-center">
      <h1 class="text-base font-semibold">{{t("app.title")}}</h1>
      <p class="text-sm text-muted-foreground">{{t("app.loadFailed")}}</p>
      <Button type="button" variant="outline" @click="retry">{{t("common.retry")}}</Button>
    </section>
  </main>
</template>
