<script setup lang="ts">
import { computed } from "vue"
import { uiPreferences } from "@/shared/lib/preferences"
import { asUtcInstant, presentInstant } from "@/shared/lib/event-time"

const props=defineProps<{value:string|null|undefined;unknownLabel?:string}>()
const utc=computed(()=>asUtcInstant(props.value))
const label=computed(()=>presentInstant(props.value,uiPreferences.locale.value,uiPreferences.displayTimeZone.value))
</script>
<template>
  <time v-if="utc && label" :datetime="utc" :title="`${utc} (UTC)`" class="tabular-nums">{{label}}</time>
  <span v-else class="text-muted-foreground">{{unknownLabel??'—'}}</span>
</template>
