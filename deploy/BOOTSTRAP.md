# Briareus first-time Coolify bootstrap contract

No live mutation has been performed. This is the exact next operational boundary after D2 source review and publication.

## Preconditions

- module-first `deploy/` source independently accepted and published to a reviewed Git ref in `ArthurKoba/briareus`;
- authorized Coolify write credential/session for `https://coolify.koba-nexus.ru`;
- exact installed Coolify version observed and passed to `bootstrap_coolify.py --expected-version`;
- target server UUID exactly `5jrwg4jddi4axlzn2lspubrn` / `tambov`;
- required secret/shared keys from `ENVIRONMENT.md` populated in Coolify environment scope without printing them;
- no existing conflicting Briareus resources with the same names/network.

## First approved mutation

Run `bootstrap_coolify.py --apply` with the reviewed branch/ref. It may only:

1. create/find project `briareus`;
2. create/find environment `development`;
3. verify required shared variables; **stop here if any key is absent**;
4. create/find standalone Destination `Briareus Network` / `briareus-net`;
5. create/find the 11 exact Applications from `APPLICATIONS.json` with auto-deploy and instant deploy disabled, no generated public domain;
6. persist Base directory `/deploy/<module>`, Compose location `/docker-compose.coolify.yaml`, reviewed branch and exact Watch Paths;
7. bind required Application variables to existing `{{environment.KEY}}` references as Runtime=true / Buildtime=false after Compose parser materialization.

The bootstrap **does not call Application start/restart/deploy**, does not initialize PostgreSQL schema, does not enable public routes and does not alter legacy MCP resources.

## Uncertain outcome / rollback

All POST operations are single-attempt and expected-state-refetched; no blind retry after transport uncertainty. Existing resources with conflicting repository/base/ownership fail closed instead of being taken over.

Because bootstrap does not start workloads, rollback is configuration-only. Newly created but undeployed Briareus resources can be retained for inspection. Any deletion of created Applications, Destination, environment/project or data volumes is a separate destructive action after exact identity review; bootstrap intentionally contains **no delete operation**. Legacy `mcp-bridge` and `ghidra-mcp` are never rollback targets.

After parser/environment reconciliation succeeds, D reports the exact resource UUIDs and parser state for independent review. Actual Data deployment/schema initialization and then individual Briareus module deployment occur as separate later approval/acceptance stages.
