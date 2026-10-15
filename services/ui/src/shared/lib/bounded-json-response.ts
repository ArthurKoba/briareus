/** Bounded, abort-aware JSON transport for same-origin Control Panel API.
 * Transport size/cancellation is a safety boundary, NOT authentication:
 * owner, grant, version and the exact DTO remain the caller's responsibility.
 *
 * The optional strict media check is for endpoints with a verified JSON
 * Content-Type contract. Existing synthetic fixtures often omit it, so
 * callers requiring production-only MIME enforcement must opt in.
 */
export async function readBoundedJsonResponse(
  response:Response,
  signal:AbortSignal,
  maxBytes:number,
  strictJsonMedia=false,
):Promise<unknown>{
  if(!Number.isSafeInteger(maxBytes)||maxBytes<1||maxBytes>8_388_608)
    throw Error("invalid response budget")
  if(strictJsonMedia&&
    response.headers.get("content-type")?.split(";",1)[0].trim().toLowerCase()!=="application/json")
    throw Error("invalid response media")
  const size=response.headers.get("content-length")
  if(size!==null&&(!/^\d{1,9}$/.test(size)||Number(size)>maxBytes))
    throw Error("invalid response length")
  if(signal.aborted||!response.body)throw Error("response cancelled or missing")
  const reader=response.body.getReader()
  let total=0
  const chunks:Uint8Array[]=[]
  let interrupt:((error:Error)=>void)|null=null
  const stopped=new Promise<never>((_resolve,reject)=>{interrupt=reject})
  const cancelReader=():void=>{try{void reader.cancel().catch(()=>{})}catch{/* no body owner */}}
  const onAbort=():void=>{interrupt?.(new Error("response cancelled"));cancelReader()}
  signal.addEventListener("abort",onAbort,{once:true})
  try{
    if(signal.aborted)throw Error("response cancelled")
    while(true){
      const part=await Promise.race([reader.read(),stopped])
      if(part.done)break
      total+=part.value.byteLength
      if(total>maxBytes)throw Error("response exceeds budget")
      chunks.push(part.value)
      if(signal.aborted)throw Error("response cancelled")
    }
  }catch(error){
    cancelReader()
    throw error
  }finally{
    signal.removeEventListener("abort",onAbort)
    reader.releaseLock()
  }
  if(signal.aborted)throw Error("response cancelled")
  const bytes=new Uint8Array(total)
  let offset=0
  for(const chunk of chunks){bytes.set(chunk,offset);offset+=chunk.byteLength}
  return JSON.parse(new TextDecoder("utf-8",{fatal:true}).decode(bytes)) as unknown
}

/** Small untrusted errors must not consume unlimited browser memory/time.
 * Valid codes never carry raw provider exceptions, cookies or identities.
 */
export async function readBoundedErrorCode(
  response:Response,signal:AbortSignal,fallback="UNAVAILABLE",
):Promise<string>{
  try{
    const result=await readBoundedJsonResponse(response,signal,4096)
    if(!result||typeof result!=="object"||Array.isArray(result))return fallback
    const error=(result as Record<string,unknown>).error
    if(!error||typeof error!=="object"||Array.isArray(error))return fallback
    const code=(error as Record<string,unknown>).code
    return typeof code==="string"&&/^[A-Z][A-Z0-9_]{0,127}$/.test(code)?code:fallback
  }catch{return fallback}
}
