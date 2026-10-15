import {onBeforeUnmount,onMounted,readonly,ref,watch} from "vue"
import {boundedLifetime,type BoundedLifetime} from "./bounded-lifetime"

/** Local presentation lifetime for a server-issued expiry, not authorization.
 * Timers and foreground checks remove stale UI even when the parent leaves
 * its props unchanged. Renewing a proof keeps a still-current scope alive.
 */
export function useProofLifetime(source:()=>string|null|undefined){
  const current=ref(false)
  let timer:ReturnType<typeof setTimeout>|null=null
  let lifetime:BoundedLifetime|null=null
  function cancel():void{if(timer!==null){clearTimeout(timer);timer=null}}
  function check():void{
    cancel()
    if(!current.value)return
    const remaining=lifetime?.remainingMilliseconds()??0
    if(!(remaining>0)){current.value=false;return}
    timer=setTimeout(check,Math.min(Math.ceil(remaining),2147483647))
  }
  watch(source,value=>{
    cancel()
    const expiry=typeof value==="string"?Date.parse(value):NaN
    lifetime=boundedLifetime(expiry)
    current.value=lifetime.remainingMilliseconds()>0
    check()
  },{immediate:true,flush:"sync"})
  function onVisible():void{if(document.visibilityState==="visible")check()}
  onMounted(()=>document.addEventListener("visibilitychange",onVisible))
  onBeforeUnmount(()=>{cancel();document.removeEventListener("visibilitychange",onVisible)})
  return readonly(current)
}
