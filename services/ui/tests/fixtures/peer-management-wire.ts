/** Actual Frontend clients against an actual peer BFF HTTP server. Only the
 * isolated Python fixture supplies artificial sessions/owner data. No UI
 * entry imports this file, no production endpoint or credential is added.
 */
import assert from 'node:assert/strict'
import {createHash} from 'node:crypto'
import {readProjectContext} from '../../src/features/platform/api/platform-current'
import type {RauthyPanelIdentity} from '../../src/features/platform/api/rauthy-oidc'
import {openVerifiedNormalSession} from '../../src/features/agent-sessions/model/open-verified'
import {createSessionOpenRecovery} from '../../src/features/agent-sessions/model/open-recovery'
import {openNormalSession} from '../../src/features/agent-sessions/api/open-normal'
import {listCurrentSessions,readCurrentSession,revokeCurrentSession} from '../../src/features/agent-sessions/api/current-sessions'
import {revokeVerifiedSession} from '../../src/features/agent-sessions/model/revoke-current'
import {requestSessionElevation} from '../../src/features/approvals/api/request-elevation'
import {readProjectApprovals} from '../../src/features/approvals/api/control-panel'
import {resolveCurrentApproval} from '../../src/features/approvals/model/resolve-current'
import {readCurrentCatalog} from '../../src/features/catalog/api/current-metadata'
import {readVerifiedFilesContent} from '../../src/features/files-preview/api/files-content'
const port=process.env.FRONTEND_WIRE_PORT
assert(port&&/^\d+$/.test(port))
const project='33333333-3333-4333-8333-333333333333',member='11111111-1111-4111-8111-111111111111',approver='22222222-2222-4222-8222-222222222222'
const filePath='wire-fixture.txt',fileSelector='project-path-v1:'+project+':'+createHash('sha256').update('files-project-relative-v1\0'+filePath).digest('hex')
let role:'member'|'approver'|'none'='member',badOrigin=false,requests=0
const wireFetch=globalThis.fetch,signal=()=>new AbortController().signal
const identity=():RauthyPanelIdentity=>({authenticated:true,authority:'rauthy',issuer:'https://identity.example.invalid/auth/v1',subject:role,client_id:'briareus-control-panel',expires_at:new Date(Date.now()+600_000).toISOString(),platform_membership_verified:false,permissions:[]})
globalThis.fetch=async(url,options)=>{
  assert(String(url).startsWith('/api/v1/'))
  assert.equal(options?.credentials,'same-origin');assert.equal(options?.redirect,'error')
  requests++
  const headers=new Headers(options?.headers)
  // Emulate only browser Origin and the private fixture's synthetic cookie.
  // Session/User/Project/command responses are NOT stubbed by this client.
  headers.set('Origin',badOrigin?'https://wrong.invalid':'https://briareus.koba-nexus.ru')
  headers.set('Host','briareus.koba-nexus.ru') // synthetic Gateway-preserved Host for the owner BFF
  if(role!=='none')headers.set('Cookie','__Host-briareus_oidc_session='+(role==='member'?'a':'b').repeat(48))
  return wireFetch('http://127.0.0.1:'+port+url,{...options,headers})
}
try{
  const memberProof=await readProjectContext(identity(),project,signal())
  assert.equal(memberProof.kind,'verified');if(memberProof.kind!=='verified')throw new Error('proof')
  assert.deepEqual(memberProof.context.projects[0]?.permissions,['use_resources'])
  const journal=createSessionOpenRecovery(),context={ownerKey:'member-wire',actorId:member,projectId:project,proofExpiresAt:memberProof.context.expires_at,canOpen:true}
  const verify=async()=>{
    const proof=await readProjectContext(identity(),project,signal())
    return proof.kind==='verified'?'authorized' as const:'unavailable' as const
  }
  const options={journal,policy:'requestable' as const,label:'lose-once',context:()=>context,verify}
  const first=await openVerifiedNormalSession({...options,saved:null,signal:signal()})
  assert.equal(first.kind,'uncertain')
  const saved=journal.get(context.ownerKey,project);assert(saved)
  const recovered=await openVerifiedNormalSession({...options,saved,signal:signal()})
  assert.equal(recovered.kind,'created');if(recovered.kind!=='created')throw new Error('created')
  assert.equal(journal.get(context.ownerKey,project),null)
  const inventory=await listCurrentSessions(project,member,false,signal())
  assert.equal(inventory.kind,'ready');if(inventory.kind!=='ready')throw new Error('inventory')
  assert.equal(inventory.items.length,1);assert.deepEqual(inventory.items[0]?.allowed_actions,[])
  badOrigin=true
  assert.equal((await openNormalSession(project,'fixed','bad-origin',signal())).kind,'forbidden')
  badOrigin=false
  const resources=[{hand:'files',tool:'read_file',action:'files.read',resource:{kind:'workspace_path',id:fileSelector}}]
  const pending=await requestSessionElevation(recovered.session,resources,60,member,signal())
  assert.equal(pending.kind,'pending')
  const pending2=await requestSessionElevation(recovered.session,resources,60,member,signal())
  assert.equal(pending2.kind,'pending')
  role='approver'
  const proof=await readProjectContext(identity(),project,signal())
  assert.equal(proof.kind,'verified');if(proof.kind!=='verified')throw new Error('approver proof')
  const approvals=await readProjectApprovals(project,signal())
  assert.equal(approvals.kind,'ready');if(approvals.kind!=='ready')throw new Error('approvals')
  assert.equal(approvals.items.length,2)
  const commandContext={projectId:project,actorId:approver,canApprove:true,proofExpiresAt:proof.context.expires_at,rows:approvals.items}
  const approved=await resolveCurrentApproval(approvals.items[0]!,'approve',{signal:signal(),context:()=>commandContext,verify})
  assert.equal(approved.kind,'confirmed');if(approved.kind!=='confirmed')throw new Error('approved')
  const childId=approved.items.find(row=>row.id===approvals.items[0]!.id)?.issued_session_uuid;assert(childId)
  const rejected=await resolveCurrentApproval(approvals.items[1]!,'deny',{signal:signal(),context:()=>commandContext,verify})
  assert.equal(rejected.kind,'confirmed')
  const child=await readCurrentSession(project,childId,approver,true,signal())
  assert.equal(child.kind,'ready');if(child.kind!=='ready')throw new Error('child')
  assert.equal(child.item.is_elevated,true)
  role='member'
  const fileRead=await readVerifiedFilesContent(child.item,filePath,8192,signal())
  assert.equal(fileRead.kind,'ready',JSON.stringify(fileRead))
  if(fileRead.kind==='ready'){
    assert.equal(fileRead.item.kind,'text')
    if(fileRead.item.kind==='text')assert.equal(fileRead.item.content,'only synthetic trusted owner bytes\n')
  }
  const invalidFileRead=await readVerifiedFilesContent(child.item,'not-allowed.txt',8192,signal())
  assert.equal(invalidFileRead.kind,'invalid')
  badOrigin=true
  const crossOriginRead=await readVerifiedFilesContent(child.item,filePath,8192,signal())
  assert.equal(crossOriginRead.kind,'forbidden')
  badOrigin=false
  role='approver'
  const revoked=await revokeVerifiedSession(child.item,{signal:signal(),context:()=>commandContext,verify})
  assert.equal(revoked.kind,'confirmed')
  assert.equal((await revokeCurrentSession(child.item,signal())).kind,'conflict')
  role='member'
  assert.equal((await readVerifiedFilesContent(child.item,filePath,8192,signal())).kind,'forbidden')
  role='approver'
  assert.equal((await readCurrentSession(project,crypto.randomUUID(),approver,true,signal())).kind,'not_found')
  for(const kind of ['integration','variable'] as const){
    const records=await readCurrentCatalog(project,kind,proof.context,signal())
    assert.equal(records.kind,'ready')
    if(records.kind==='ready')assert.equal(records.items[0]?.key,'wire.metadata')
  }
  role='none'
  assert.equal((await readProjectContext(identity(),project,signal())).kind,'signed_out')
  console.log('LOCAL_BFF_HTTP_CLIENTS_PASS create/replay/list/detail/request/approve/deny/revoke/catalog/401/403/409/404',requests)
}finally{globalThis.fetch=wireFetch}
