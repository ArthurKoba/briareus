import {describe,expect,it} from "bun:test"
import {solveRauthyPow,validRauthyPowChallenge} from "../src/features/platform/model/rauthy-pow"

const challenge=(difficulty:number,expiry:number)=>
  `1:${String(difficulty).padStart(2,"0")}:${expiry}:${"A".repeat(16)}:${"B".repeat(43)}:`

describe("official Rauthy public sPoW 0.7 solver boundary",()=>{
  it("accepts only recent bounded version-one public challenge shapes",()=>{
    const now=1_798_000_000
    expect(validRauthyPowChallenge(challenge(20,now+40),now)).toBe(true)
    expect(validRauthyPowChallenge(challenge(10,now),now)).toBe(true)
    for(const input of [
      challenge(20,now-1),challenge(20,now+181),challenge(9,now+30),challenge(25,now+30),
      challenge(99,now+30),"2"+challenge(20,now+30).slice(1),
      challenge(20,now+30)+"additional",challenge(20,now+30).replace("A","%"),
      {challenge:challenge(20,now+30)},null,
    ])expect(validRauthyPowChallenge(input,now)).toBe(false)
  })
  it("rejects aborted/malformed challenges without starting any background work",async()=>{
    expect(await solveRauthyPow("bad",new AbortController().signal)).toEqual({kind:"unavailable"})
    expect(await solveRauthyPow(challenge(20,Math.floor(Date.now()/1000)+40),AbortSignal.abort()))
      .toEqual({kind:"cancelled"})
  })
})
