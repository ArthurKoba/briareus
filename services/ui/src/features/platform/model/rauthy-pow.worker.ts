/** Official Rauthy 0.37.1 sPoW 0.7.0 WebAssembly in an isolated worker.
 * Challenge is PUBLIC. Worker has no identity/session/credential BFF access.
 * Backend/IdP validate PoW; solving never authenticates a browser.
 */
import wasmUrl from "../vendor/spow/spow-wasm_bg.wasm?url"
import {__wbg_set_wasm,__wbindgen_init_externref_table,pow_work_wasm} from "../vendor/spow/spow-wasm_bg.js"

const INPUT=/^1:(\d{2}):(\d{10}):([A-Za-z0-9+/]{16}):([A-Za-z0-9+/]{43}):$/
function validChallenge(input:unknown):input is string{
  if(typeof input!=="string"||input.length>128)return false
  const parts=INPUT.exec(input)
  if(!parts)return false
  const difficulty=Number(parts[1]),expires=Number(parts[2]),now=Math.floor(Date.now()/1000)
  // Rauthy's pinned local default is 20. Never run unbounded work on
  // malformed or unexpectedly high upstream difficulty.
  return difficulty>=10&&difficulty<=24&&expires>=now&&expires<=now+180
}
self.onmessage=async (event:MessageEvent<unknown>):Promise<void>=>{
  try{
    const challenge=event.data
    if(!validChallenge(challenge))throw Error("invalid challenge")
    // Vite's library/browser-worker bundles inline this pinned 37KiB WASM
    // into a data URI. Fetching a data URI with mode:same-origin is denied
    // by the browser; it needs no credentials and has no network target.
    const inline=wasmUrl.startsWith("data:application/wasm;base64,")
    const response=inline?await fetch(wasmUrl):await fetch(wasmUrl,{
      credentials:"same-origin",mode:"same-origin",redirect:"error",cache:"force-cache",
    })
    if(!response.ok)throw Error("upstream solver missing")
    const size=response.headers.get("content-length")
    if(size!==null&&(!/^\d{1,6}$/.test(size)||Number(size)>65536))throw Error("unexpected solver asset")
    const bytes=await response.arrayBuffer()
    if(bytes.byteLength>65536)throw Error("oversized solver asset")
    const module=await WebAssembly.compile(bytes)
    const instance=await WebAssembly.instantiate(module,{"./spow-wasm_bg.js":{__wbindgen_init_externref_table}})
    __wbg_set_wasm(instance.exports)
    ;(instance.exports.__wbindgen_start as ()=>void)()
    const solved=pow_work_wasm(challenge)
    if(typeof solved!=="string"||solved.length>128||!solved.startsWith(challenge)||
       !/^\d+$/.test(solved.slice(challenge.length)))throw Error("bad work")
    self.postMessage({kind:"solved",work:solved})
  }catch{
    self.postMessage({kind:"unavailable"})
  }finally{
    self.close()
  }
}
