/** Local deadline, never an authorization grant. Either clock may shorten
 * the lifetime; wall-clock rollback cannot extend elapsed monotonic time.
 * Once observed expired, this particular deadline cannot become live again.
 */
export interface BoundedLifetime { remainingMilliseconds():number }
export function boundedLifetime(expiresAt:number):BoundedLifetime {
  const duration=expiresAt-Date.now()
  const monotonic=performance.now()+duration
  let elapsed=!Number.isFinite(duration)||duration<=0
  return Object.freeze({remainingMilliseconds():number {
    if(elapsed)return 0
    const remaining=Math.min(expiresAt-Date.now(),monotonic-performance.now())
    if(!Number.isFinite(remaining)||remaining<=0){elapsed=true;return 0}
    return remaining
  }})
}
