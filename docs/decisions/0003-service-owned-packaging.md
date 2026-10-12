# ADR 0003 — retired historical packaging approach

**Status: SUPERSEDED by explicit owner decision 2026-10-12.**

Do not implement old exact per-file copy/watch, global Python wheel, service source distributed under common and deploy/<module>, or extra stop-before-publish approval machinery.

Current authoritative target: ../architecture/owner-decisions-20261012.md.
Service-folder migration: ../operations/service-layout-transition.md.
Agent assignments: ../operations/agent-migration-plan-20261012.md.

A service is a self-contained folder with source, Dockerfile, Compose and its uv/Bun lock; docs mirrored outside source and shared code imported through small topical folders. Current Coolify app identities/data/volumes preserved during each phased cutover. Historical full ADR remains in local/artifacts/owner-policy-reconciliation-20261012/originals/repo/docs/decisions/0003-service-owned-packaging.md for provenance, not active configuration authority.
