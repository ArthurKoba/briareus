# Pinned sPoW browser worker distribution

Upstream: `sebadob/spow` v0.7.0, Git commit `f0dc9ede0e9013ae07e97fcbf21ffab16ce53282`.

Licensed under Apache License 2.0 (see `LICENSE`). Vendored without changes from `prebuilt/browser/wasm/`:

- `spow-wasm_bg.wasm`: SHA-256 `9f541c656d00ab5b9705a47cc5942bc4194d3efb7e24509dbcc0af2f05571839`
- `spow-wasm_bg.js`: SHA-256 `92ff08340687902d42ee90f5fdb7af9a4907e20ff21a408fc1da7aea30b149a9`
- `spow-wasm_bg.d.ts`: minimal local TypeScript declaration for the pinned JS glue (not upstream-authored).

Rauthy v0.37.1 `frontend/src/workers/pow.ts` calls upstream `pow_work_wasm` directly.
The application imports this as a **separate Web Worker**; never on the UI thread.
The worker receives no email/password, user bearer, cookie, CSRF, OAuth code or Cedar permission.
A result is only the public challenge plus work counter; provider alone accepts it.
A signed login/session/Platform permission is never inferred from successful PoW.
