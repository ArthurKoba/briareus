# D2 publication provenance

Repository: `ArthurKoba/briareus`.

Observed remote state on 2026-10-09:

- PR #410 (`feat(briareus): publish accepted greenfield DEV source and Compose`) was merged into `main` at 2026-10-09T16:52:07Z.
- Merge commit: `8192c860bb4a70ad91ff4a4f2483fa9a6261264a`.
- That published snapshot still contains the **superseded** provider-parent deployment layout and must not be used as the final module-first deployment source.
- Central local integration branch currently contains the accepted old-layout source plus later deployment repository correction, but D2 deliberately does not modify central tracked source before independent review.

The next reviewed publication must be one coherent Git delta that:

1. deletes the old provider-parent deployment tree;
2. adds this complete staged `deploy/` tree with eleven module directories and provider-neutral management files;
3. removes the obsolete duplicate `scripts/greenfield_schema.py` only after confirming the staged `deploy/data/greenfield_schema.py` is the sole intended deployment initializer and no Backend-owned source consumer still imports the old path;
4. preserves application code under `services/**` and `admin-web-app/**` unchanged by D2;
5. records an immutable review commit SHA and uses that exact reviewed branch/ref in Coolify bootstrap.

D2 does not commit, push, open a PR or publish images. Those happen only after independent orchestrator acceptance and explicit publication authorization.
