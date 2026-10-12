# Shared primitives and contracts

Small, owner-approved reusable DTOs, narrow transport/telemetry helpers, and security primitives only. Never place a service's database tables, business policy, credential authority, runtime, or large generic wheel here. `services/<name>` and `hands/<hand>` opt in to only actually imported `shared/<topic>/**` Watch paths.
