#!/bin/sh
set -eu

envsubst '${MANAGEMENT_UI_PREVIEW}' \
    < /usr/share/nginx/html/runtime-config.template.js \
    > /usr/share/nginx/html/runtime-config.js
