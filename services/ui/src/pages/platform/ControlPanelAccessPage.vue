<script setup lang="ts">
import {computed} from "vue"
import type {RauthyPanelState} from "@/features/platform/api/rauthy-oidc"
import RauthySignIn from "@/features/platform/ui/RauthySignIn.vue"

/** One honest browser login state. No speculative Init/Cancel button,
 * inactive credential placeholders, provider details or hosted login link.
 * Rauthy and Platform proof remain exclusively owned by Backend/parent.
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
const initialState=computed<RauthyPanelState|null>(()=>
  props.designPreview?{kind:"signed_out"}:props.initialSession??null)
</script>

<template>
  <div class="mx-auto w-full max-w-lg py-6 sm:py-12">
    <RauthySignIn :initial-state="initialState" :managed-logout="managedLogout"
      @logout-requested="emit('logoutRequested')"
      @state="emit('providerState',$event)"/>
  </div>
</template>
