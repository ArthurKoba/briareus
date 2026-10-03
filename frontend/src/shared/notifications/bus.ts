import { readonly, ref } from "vue"

export type NotificationLevel = "info" | "success" | "warning" | "error"
export interface AppNotification { id: number; level: NotificationLevel; title: string; description?: string; actionLabel?: string; action?: () => void; timeoutMs?: number }
const items = ref<AppNotification[]>([])
let nextId = 1
function push(value: Omit<AppNotification,"id">): number { const id=nextId++; items.value.push({id,...value}); const timeout=value.timeoutMs ?? (value.level==="error"?7000:4000); if(timeout>0) window.setTimeout(()=>remove(id),timeout); return id }
function remove(id:number): void { items.value=items.value.filter(item=>item.id!==id) }
export const notifications = { items: readonly(items), push, remove, info:(title:string,description?:string)=>push({level:"info",title,description}), success:(title:string,description?:string)=>push({level:"success",title,description}), warning:(title:string,description?:string)=>push({level:"warning",title,description}), error:(title:string,description?:string)=>push({level:"error",title,description}) }
