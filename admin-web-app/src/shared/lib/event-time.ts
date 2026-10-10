/**
 * Strict UTC-aware event-time presentation. Server UTC/offset instants are
 * authoritative for data; browser clocks only control local display and
 * countdown hints. No fabricated timezone, Team TZ ENV or OS audit inference.
 */
export type TimePresentation = "UTC" | "system"
export type TimeLocale = "ru" | "en"

/** Preserve only real timezone-aware ISO-8601 wire timestamps. */
export function asUtcInstant(value:string|null|undefined):string|null {
  if(typeof value!=="string"||value.length>64||
    !/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}(:\d{2}(?:\.\d{1,6})?)?(Z|[+-]\d{2}:\d{2})$/i.test(value))return null
  const time=Date.parse(value)
  if(!Number.isFinite(time))return null
  try {return new Date(time).toISOString()}
  catch {return null}
}
export function presentInstant(value:string|null|undefined,locale:TimeLocale,mode:TimePresentation):string|null {
  const instant=asUtcInstant(value)
  if(!instant)return null
  // This is UI rendering, never reinterpretation of a stored instant.
  const config:Intl.DateTimeFormatOptions={
    year:"numeric",month:"short",day:"2-digit",hour:"2-digit",minute:"2-digit",second:"2-digit",
    hour12:false,timeZoneName:"short",
  }
  if(mode==="UTC")config.timeZone="UTC"
  return new Intl.DateTimeFormat(locale==="ru"?"ru-RU":"en-US",config).format(new Date(instant))
}
/** Native datetime-local fields are explicitly DEVICE-local regardless of
 * the separate timestamp display choice. Backend receives ISO UTC via
 * Date#toISOString after user explicitly edits a local wall-clock value. */
export function deviceLocalInput(instant:string|null|undefined):string {
  const utc=asUtcInstant(instant)
  if(!utc)return ""
  const date=new Date(utc)
  return new Date(date.getTime()-date.getTimezoneOffset()*60_000).toISOString().slice(0,16)
}
export function deviceInputToUtc(value:string):string|null {
  if(!/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}$/.test(value))return null
  const date=new Date(value)
  const millis=date.getTime()
  if(!Number.isFinite(millis))return null
  const utc=date.toISOString()
  // DST spring-forward silently normalizes a nonexistent wall-clock time.
  // Reject instead of sending a DIFFERENT deadline to a privileged API.
  if(deviceLocalInput(utc)!==value)return null
  // DST fall-back can produce TWO distinct real instants for one local input.
  // The native datetime-local control has no disambiguation field; reject.
  for(const minuteDelta of [-120,-90,-60,-30,30,60,90,120]){
    if(deviceLocalInput(new Date(millis+minuteDelta*60_000).toISOString())===value)return null
  }
  return utc
}
