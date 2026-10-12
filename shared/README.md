# Shared Hand libraries

`shared/` is a repository-root sibling of `hands/` and `services/`.
Shared code is organized by independently owned packages: `shared/<package>/`.
Do not place executable application entrypoints or privileged deployment
configuration here. A Hand explicitly selects and packages only the modules
it imports, with a tracked dependency/version contract.

Each consuming Hand includes precisely `shared/<package>/**` in its Coolify
Watch Paths alongside `hands/<hand>/**`, and includes the package in its own
Docker build. Updating one shared package must not trigger unrelated Hands.
Ownership for each new package must be recorded in coordination before two
agent lanes can edit it; no global `shared/**` watcher is permitted.

`shared/hand_runtime` supplies the fail-closed ASGI building block for the staged
SVC Hand. It is source-packaged into that Hand image and included as an
explicit watch dependency. It does not authenticate Rauthy users or perform
Cedar authorization.
