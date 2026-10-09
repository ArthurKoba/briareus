/** Accepted Backend A6: keyset pages are individually authorized, NOT snapshots. */
import {
  DraftContractError,draftBoolean,draftInteger,draftList,draftRecordFields,draftSessionUuid,
} from "@/features/platform/api/draft/source-contract"

export interface SourceKeysetPage<T> {
  items:T[]
  next_after_id:string|null
  has_more:boolean
  page_size:number
}
export const A6_PAGE_SIZE=100
export function checkedPageLimit(limit:number):number {
  if(!Number.isInteger(limit)||limit<1||limit>250)throw new DraftContractError("source_page_size_invalid")
  return limit
}
export function checkedPageAfter(after:string|null|undefined):string|null {
  return after==null?null:draftSessionUuid(after)
}
export function sourcePageQuery(limit=A6_PAGE_SIZE,after?:string|null):string {
  const query=new URLSearchParams({limit:String(checkedPageLimit(limit))})
  const cursor=checkedPageAfter(after)
  if(cursor)query.set("after",cursor)
  return `?${query.toString()}`
}
export function parseSourcePage<T>(raw:unknown,read:(value:unknown)=>T,idOf:(item:T)=>string,
  requestedLimit=A6_PAGE_SIZE,requestedAfter?:string|null):SourceKeysetPage<T> {
  const v=draftRecordFields(raw,["items","next_after_id","has_more","page_size"])
  const items=draftList(v.items,read)
  const has_more=draftBoolean(v.has_more)
  const page_size=checkedPageLimit(draftInteger(v.page_size))
  if(page_size!==checkedPageLimit(requestedLimit)||items.length>page_size)
    throw new DraftContractError("source_page_size_mismatch")
  const next_after_id=v.next_after_id===null?null:checkedPageAfter(v.next_after_id as string)
  const previous=checkedPageAfter(requestedAfter)
  let last=previous
  for(const item of items){
    const id=checkedPageAfter(idOf(item))
    if(!id||last&&id<=last)throw new DraftContractError("source_page_not_ordered")
    last=id
  }
  if(has_more){
    if(!items.length||!next_after_id||next_after_id!==last)
      throw new DraftContractError("source_page_cursor_missing")
  }else if(next_after_id!==null){
    throw new DraftContractError("source_page_terminal_cursor_invalid")
  }
  return {items,next_after_id,has_more,page_size}
}
