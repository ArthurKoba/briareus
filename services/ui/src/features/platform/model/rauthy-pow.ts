/** Public Proof-of-Work precomputation, not credential validation.
 * A worker has the bounded public challenge only; no passwords, tokens or
 * crypto secrets are sent to it. Never run CPU loops on the main UI thread.
 */
export type PowWorkResult={kind:"solved";work:string}|{kind:"unavailable"|"cancelled"}
const FORMAT=/^1:(\d{2}):(\d{10}):[A-Za-z0-9+/]{16}:[A-Za-z0-9+/]{43}:$/
export function validRauthyPowChallenge(raw:unknown,now=Math.floor(Date.now()/1000)):raw is string{
  if(typeof raw!=="string"||raw.length>128)return false
  const matches=FORMAT.exec(raw)
  if(!matches||!Number.isFinite(now))return false
  const difficulty=Number(matches[1]),expires=Number(matches[2])
  return difficulty>=10&&difficulty<=24&&expires>=now&&expires<=now+180
}
export async function solveRauthyPow(challenge:string,signal:AbortSignal):Promise<PowWorkResult>{
  if(signal.aborted)return {kind:"cancelled"}
  if(!validRauthyPowChallenge(challenge))return {kind:"unavailable"}
  if(typeof Worker==="undefined")return {kind:"unavailable"}
  let worker:Worker
  try{
    worker=new Worker(new URL("./rauthy-pow.worker.ts",import.meta.url),{type:"module",name:"briareus-rauthy-spow"})
  }catch{return {kind:"unavailable"}}
  return await new Promise(resolve=>{
    let settled=false
    const finish=(result:PowWorkResult):void=>{
      if(settled)return
      settled=true
      signal.removeEventListener("abort",onAbort)
      clearTimeout(deadline)
      worker.terminate()
      resolve(result)
    }
    const onAbort=():void=>finish({kind:"cancelled"})
    worker.onmessage=(event:MessageEvent<unknown>):void=>{
      const data=event.data
      if(data&&typeof data==="object"&&"kind" in data&&data.kind==="solved"&&
         "work" in data&&typeof data.work==="string"&&data.work.length<=128&&
         data.work.startsWith(challenge)&&/^\d+$/.test(data.work.slice(challenge.length))){
        finish({kind:"solved",work:data.work})
      }else finish({kind:"unavailable"})
    }
    worker.onerror=():void=>finish({kind:"unavailable"})
    const deadline=setTimeout(()=>finish({kind:"unavailable"}),30000)
    signal.addEventListener("abort",onAbort,{once:true})
    if(signal.aborted){onAbort();return}
    try{worker.postMessage(challenge)}catch{finish({kind:"unavailable"})}
  })
}
