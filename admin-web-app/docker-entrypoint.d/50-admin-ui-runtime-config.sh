#!/bin/sh
set -eu
# No runtime ENV configuration exists for Briareus. This inert entrypoint
# remains only until Deployment removes its Dockerfile COPY and this hook.
exit 0
