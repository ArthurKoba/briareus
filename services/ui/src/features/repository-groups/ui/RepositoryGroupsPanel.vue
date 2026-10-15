<script setup lang="ts">
import { computed } from "vue"
import { useI18n } from "vue-i18n"
import { FolderGit2 } from "lucide-vue-next"
import { Card,CardContent,CardHeader,CardTitle } from "@/shared/ui/card"
import { Button } from "@/shared/ui/button"
const {locale}=useI18n()
const label=computed(()=>locale.value==="ru"?{
 title:"Группы репозиториев",description:"Группируйте репозитории GitHub и GitLab по проектам или рабочим областям. Список и операции доступны только через подтверждённый BFF.",create:"Создать группу",empty:"Подтверждённых групп пока нет",missing:"Создание, членство и удаление групп ожидают Backend API."
}:{
 title:"Repository groups",description:"Organize GitHub and GitLab repositories by project or workspace. Listing and mutations require verified BFF access.",create:"Create group",empty:"No verified groups",missing:"Group create, membership and deletion need a Backend API."
})
</script>
<template>
  <Card>
    <CardHeader class="flex flex-row flex-wrap items-start justify-between gap-3">
      <div class="min-w-0"><CardTitle class="flex items-center gap-2 text-sm"><FolderGit2 class="size-4"/>{{label.title}}</CardTitle>
        <p class="mt-2 text-xs leading-5 text-muted-foreground">{{label.description}}</p>
      </div>
      <Button variant="outline" size="sm" disabled :title="label.missing">{{label.create}}</Button>
    </CardHeader>
    <CardContent>
      <p role="status" class="rounded-lg border border-dashed border-border p-5 text-center text-sm text-muted-foreground">{{label.empty}}. {{label.missing}}</p>
    </CardContent>
  </Card>
</template>
