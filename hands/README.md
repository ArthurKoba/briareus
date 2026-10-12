# Independently deployed MCP Hands

Each MCP/tool provider lives in `hands/<hand>/` with its own src, Dockerfile, Compose, dependencies/lock, runtime, protected ingress and lifecycle. This root is owned by the Runtime lane. Existing `services/hands/<hand>` and `deploy/<hand>` remain transitional rollback; relocate individually without restarting API/UI/Authorization/other Hands. Every Hand enforces live tool/effect permissions with Authorization, even when Gateway already admitted the MCP connection.
