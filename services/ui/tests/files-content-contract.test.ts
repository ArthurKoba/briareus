import {afterEach,describe,expect,it} from "bun:test"
import {createHash} from "node:crypto"
import {readVerifiedFilesContent,type FilesReadSessionReference} from "../src/features/files-preview/api/files-content"

const project="11111111-1111-4111-8111-111111111111"
const session="22222222-2222-4222-8222-222222222222"
const path="documents/README.md"
const selector=(filename:string)=>"project-path-v1:"+project+":"+
  createHash("sha256").update("files-project-relative-v1\0"+filename).digest("hex")
function source(filename=path):FilesReadSessionReference{
  return {project_uuid:project,session_uuid:session,revision:7,status:"active",
    hard_expires_at:new Date(Date.now()+45_000).toISOString(),operations:["files.read"],
    resources:[{hand:"files",tool:"read_file",action:"files.read",resource:{kind:"workspace_path",id:selector(filename)}}]}
}
function payload(data:string= "Hello, Briareus"){
  const bytes=Buffer.from(data,"utf8")
  return {path,size_bytes:bytes.length,sha256:createHash("sha256").update(bytes).digest("hex"),content_base64:bytes.toString("base64")}
}
function response(status:number,data:unknown):Response{
  return new Response(JSON.stringify(data),{status,headers:{"Content-Type":"application/json"}})
}
const original=globalThis.fetch
afterEach(()=>{globalThis.fetch=original})

describe("versioned source-only Files content BFF client",()=>{
  it("sends only exact Project/session/revision/path/budget with no browser grants",async()=>{
    let count=0,postBody:Record<string,unknown>|null=null,postOptions:RequestInit|undefined
    globalThis.fetch=async(url,options)=>{
      count++
      expect(url).toBe("/api/v1/files/read")
      postOptions=options
      postBody=JSON.parse(String(options?.body)) as Record<string,unknown>
      return response(200,payload())
    }
    const result=await readVerifiedFilesContent(source(),path,262_144,new AbortController().signal)
    expect(result.kind).toBe("ready")
    if(result.kind==="ready")expect(result.item).toMatchObject({kind:"text",content:"Hello, Briareus"})
    expect(count).toBe(1)
    expect(postBody).toEqual({project_uuid:project,agent_session_uuid:session,
      expected_grant_revision:7,path,max_bytes:262_144})
    expect(postOptions?.method).toBe("POST")
    expect(postOptions?.credentials).toBe("same-origin")
    expect(postOptions?.redirect).toBe("error")
    expect(postOptions?.mode).toBe("same-origin")
    expect(postOptions?.cache).toBe("no-store")
    expect(postOptions?.headers).toEqual({Accept:"application/json","Content-Type":"application/json"})
  })
  it("requires one exact owner selector, never invents a Files grant from files.read alone",async()=>{
    let calls=0
    globalThis.fetch=async()=>{calls++;throw Error("unexpected HTTP effect")}
    const noScope={...source(),resources:[]}
    const foreign={...source("another-file.txt")}
    const expired={...source(),hard_expires_at:new Date(Date.now()-1000).toISOString()}
    const revoked={...source(),status:"revoked" as const}
    for(const [record,filename,budget] of [
      [noScope,path,8192],[foreign,path,8192],[expired,path,8192],
      [revoked,path,8192],[source(),"../escape",8192],
      [source(),"documents//empty",8192],[source(),"/absolute",8192],
      [source(),path,262145],[source(),path,0],
      [source(),"cafe\u0301",8192],
    ] as const){
      const result=await readVerifiedFilesContent(record,filename,budget,new AbortController().signal)
      expect(result.kind).toBe("invalid")
    }
    expect(calls).toBe(0)
  })
  it("maps owner unavailability and denials but never exposes arbitrary server text",async()=>{
    for(const [code,kind] of [[401,"unauthorized"],[403,"forbidden"],[422,"invalid"],[503,"unavailable"],[404,"unavailable"]] as const){
      let calls=0
      globalThis.fetch=async()=>{calls++;return response(code,{error:{code:"FILES_READ_OWNER_UNAVAILABLE"}})}
      const result=await readVerifiedFilesContent(source(),path,64,new AbortController().signal)
      expect(result.kind).toBe(kind)
      expect(calls).toBe(1)
    }
  })
  it("rejects mismatched checksum, foreign path and oversized response instead of showing file content",async()=>{
    const good=payload()
    for(const damaged of [
      {...good,sha256:"0".repeat(64)},
      {...good,path:"other.md"},
      {...good,size_bytes:good.size_bytes+1},
      {...good,content_base64:good.content_base64+"AA"},
      {...good,extra:"forged auth"},
    ]){
      globalThis.fetch=async()=>response(200,damaged)
      expect((await readVerifiedFilesContent(source(),path,8192,new AbortController().signal)).kind).toBe("invalid")
    }
    globalThis.fetch=async()=>new Response(JSON.stringify(good),{
      status:200,headers:{"Content-Type":"text/html"},
    })
    expect((await readVerifiedFilesContent(source(),path,8192,new AbortController().signal)).kind).toBe("invalid")
    globalThis.fetch=async()=>new Response("X".repeat(400_000),{status:200})
    expect((await readVerifiedFilesContent(source(),path,8192,new AbortController().signal)).kind).not.toBe("ready")
  })
  it("does not display a late success after cancellation, or fetch after preflight cancellation",async()=>{
    const stopped=AbortSignal.abort()
    let calls=0
    globalThis.fetch=async()=>{calls++;return response(200,payload())}
    expect((await readVerifiedFilesContent(source(),path,256,stopped)).kind).toBe("cancelled")
    expect(calls).toBe(0)
    const request=new AbortController()
    globalThis.fetch=async()=>{calls++;request.abort();return response(200,payload())}
    expect((await readVerifiedFilesContent(source(),path,256,request.signal)).kind).toBe("cancelled")
    expect(calls).toBe(1)
  })
})
