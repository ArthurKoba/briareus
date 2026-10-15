import {describe,expect,it} from "bun:test"
import {decodeFilesReadResult,MAX_FILES_READ_BYTES} from "../src/features/files-preview/model/read-result"
async function payload(content:string|Uint8Array,path="src/main.ts"){
  const bytes=typeof content==="string"?new TextEncoder().encode(content):content
  const buffer=new Uint8Array(bytes)
  const digest=await crypto.subtle.digest("SHA-256",buffer)
  const sha256=Array.from(new Uint8Array(digest),byte=>byte.toString(16).padStart(2,"0")).join("")
  return {path,size_bytes:bytes.length,sha256,content_base64:Buffer.from(bytes).toString("base64")}
}
describe("bounded Files read response preview (not authorization)",()=>{
  it("decodes UTF-8 bytes exactly and leaves HTML as plain text",async()=>{
    const text='<script>not executed</script>\nПривет, Rīga'
    const result=await decodeFilesReadResult(await payload(text),"src/main.ts")
    expect(result.kind).toBe("text")
    if(result.kind==="text")expect(result.content).toBe(text)
    expect(await decodeFilesReadResult(await payload(""),"src/main.ts")).toMatchObject({kind:"text",content:"",sizeBytes:0})
  })
  it("rejects foreign paths, extra fields, byte-count mismatch and checksum mutation",async()=>{
    const good=await payload("text")
    for(const bad of [
      {...good,path:"other.ts"},{...good,grant:true},{...good,size_bytes:5},
      {...good,sha256:"0".repeat(64)},{...good,content_base64:good.content_base64+"\n"},
    ])expect((await decodeFilesReadResult(bad,"src/main.ts")).kind).toBe("invalid")
  })
  it("does not accept traversal, absolute, reserved, non-NFC or malformed Unicode paths",async()=>{
    for(const path of ["../file","/etc/passwd","a//b","a/./b","a\\b","a\u0000b","e\u0301.txt",
      ".upload-"+"a".repeat(32)+".tmp","a".repeat(256),"\ud800"]){
      expect((await decodeFilesReadResult(await payload("text",path),path)).kind).toBe("invalid")
    }
  })
  it("keeps non-UTF8 and control bytes out of text rendering",async()=>{
    for(const bytes of [new Uint8Array([255,254]),new Uint8Array([65,0,66])]){
      expect((await decodeFilesReadResult(await payload(bytes),"src/main.ts")).kind).toBe("binary")
    }
  })
  it("bounds reads before decoding and rejects noncanonical base64 pad bits",async()=>{
    const good=await payload("a")
    expect((await decodeFilesReadResult({...good,content_base64:"YR=="},"src/main.ts")).kind).toBe("invalid")
    expect((await decodeFilesReadResult({...good,size_bytes:MAX_FILES_READ_BYTES+1},"src/main.ts")).kind).toBe("invalid")
    expect((await decodeFilesReadResult(await payload("ab"),"src/main.ts",undefined,1)).kind).toBe("invalid")
    expect((await decodeFilesReadResult(good,"src/main.ts",AbortSignal.abort())).kind).toBe("cancelled")
  })
})

describe("bounded searchable Files text pages",()=>{
  it("reconstructs every accepted character across pages without splitting Unicode or CRLF",async()=>{
    const {buildTextPreview,PREVIEW_PAGE_SIZE}=await import('../src/features/files-preview/model/text-window')
    for(const text of ['','a'.repeat(PREVIEW_PAGE_SIZE-1)+'🙂tail','a'.repeat(PREVIEW_PAGE_SIZE-1)+'\r\nnext',('Привет\n').repeat(8000)]){
      const preview=buildTextPreview(text)
      expect(preview.pages.map(page=>preview.text.slice(page.start,page.end)).join('')).toBe(text)
      expect(preview.pages.every(page=>page.end-page.start<=PREVIEW_PAGE_SIZE)).toBe(true)
      for(const page of preview.pages){
        const slice=preview.text.slice(page.start,page.end)
        expect(slice.isWellFormed()).toBe(true)
        expect(!(slice.endsWith('\r')&&preview.text[page.end]==='\n')).toBe(true)
      }
    }
  })
  it("finds literal text outside the former 64KiB window and bounds search results",async()=>{
    const {buildTextPreview,findTextMatches,pageForMatch}=await import('../src/features/files-preview/model/text-window')
    const preview=buildTextPreview('x'.repeat(70_000)+'<script>literal</script>'+'y'.repeat(9000))
    const matches=findTextMatches(preview.text,'<script>')
    expect(matches.positions).toEqual([70_000])
    expect(pageForMatch(preview.pages,matches.positions[0]!)).toBeGreaterThan(0)
    expect(findTextMatches('x'.repeat(600),'x')).toMatchObject({limited:true})
    expect(findTextMatches('x'.repeat(600),'x').positions).toHaveLength(500)
    expect(findTextMatches(preview.text,'[').positions).toEqual([])
    expect(findTextMatches(preview.text,'').positions).toEqual([])
  })
  it("caps oversized local display input and resets empty page metadata",async()=>{
    const {buildTextPreview,PREVIEW_TEXT_LIMIT}=await import('../src/features/files-preview/model/text-window')
    expect(buildTextPreview('a'.repeat(PREVIEW_TEXT_LIMIT+1))).toMatchObject({truncated:true})
    expect(buildTextPreview('').pages).toEqual([{start:0,end:0,firstLine:1,lastLine:1}])
  })
})
