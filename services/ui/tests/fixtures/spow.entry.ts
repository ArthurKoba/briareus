/** Isolated Rauthy sPoW worker browser fixture. No product API or credentials. */
import {solveRauthyPow,validRauthyPowChallenge} from "../../src/features/platform/model/rauthy-pow"
const output=document.querySelector("#status")
if(output)output.textContent="worker-ready"
const host=window as Window&{
  __spowFixture?:{
    solve:(challenge:string)=>Promise<unknown>
    invalid:(challenge:string)=>boolean
    abort:(challenge:string)=>Promise<unknown>
    abortInFlight:(challenge:string)=>Promise<unknown>
  }
}
host.__spowFixture={
  solve:(challenge:string)=>solveRauthyPow(challenge,new AbortController().signal),
  invalid:(challenge:string)=>validRauthyPowChallenge(challenge),
  abort:(challenge:string)=>solveRauthyPow(challenge,AbortSignal.abort()),
  abortInFlight:(challenge:string)=>{
    const operation=new AbortController()
    const pending=solveRauthyPow(challenge,operation.signal)
    setTimeout(()=>operation.abort(),25)
    return pending
  },
}
