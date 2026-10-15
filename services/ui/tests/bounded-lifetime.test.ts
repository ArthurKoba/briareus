import {describe,expect,it} from "bun:test"
import {boundedLifetime} from "../src/shared/lib/bounded-lifetime"

describe("monotonic presentation lifetime, not a server grant",()=>{
  it("wall-clock rollback cannot extend the original elapsed owner lease",async()=>{
    const realNow=Date.now
    let offset=0
    Date.now=()=>realNow()+offset
    try{
      const lease=boundedLifetime(Date.now()+20)
      expect(lease.remainingMilliseconds()).toBeGreaterThan(0)
      offset=-60_000
      await Bun.sleep(36)
      expect(lease.remainingMilliseconds()).toBe(0)
      // Moving wall time back and forth cannot resurrect a consumed proof.
      offset=-120_000
      expect(lease.remainingMilliseconds()).toBe(0)
      offset=0
      expect(lease.remainingMilliseconds()).toBe(0)
    }finally{Date.now=realNow}
  })
  it("latches earliest elapsed wall deadline and rejects invalid expiry",()=>{
    const realNow=Date.now
    let offset=0
    Date.now=()=>realNow()+offset
    try{
      const lease=boundedLifetime(Date.now()+500)
      offset=600
      expect(lease.remainingMilliseconds()).toBe(0)
      offset=-60_000
      expect(lease.remainingMilliseconds()).toBe(0)
      expect(boundedLifetime(Number.NaN).remainingMilliseconds()).toBe(0)
    }finally{Date.now=realNow}
  })
})
