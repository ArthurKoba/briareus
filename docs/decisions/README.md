# Architecture decisions

Significant architectural choices should be recorded as Architecture Decision Records (ADRs).

This directory is intentionally lightweight. Add an ADR when a decision would otherwise be repeatedly re-litigated or cannot be inferred safely from code.

Accepted ADRs:

- [ADR 0001: Provider account administration](0001-account-administration.md)
- [ADR 0003: Service-owned deployment packaging](0003-service-owned-packaging.md)

Proposed ADRs:

- [ADR 0002: Persistent terminal workspaces](0002-terminal-workspaces.md)

Remaining ADR candidates:

- modular runtime/service boundaries;
- aggregate gateway and dedicated public surface policy;
- Files data-plane ownership and cross-runtime access model;
- explicit provider `account_id` identity model.

Suggested filename convention:

```text
0001-short-decision-title.md
0002-next-decision.md
```

A minimal ADR should state context, decision, consequences and status.
