FROM oven/bun:1.4.2-alpine AS build
WORKDIR /app
COPY admin-web-app/package.json admin-web-app/bun.lock ./
RUN bun install --frozen-lockfile
COPY admin-web-app/components.json admin-web-app/index.html admin-web-app/tsconfig.json admin-web-app/vite.config.ts ./
COPY admin-web-app/src ./src
COPY admin-web-app/public ./public
RUN bun run build

FROM nginx:1.28-alpine
ENV ADMIN_UI_PREVIEW=false \
    ADMIN_API_BASE_URL= \
    ADMIN_UI_TELEMETRY_ENABLED=true \
    ADMIN_UI_TELEMETRY_SAMPLE_RATE=1 \
    ADMIN_UI_EVENTS_MODE=websocket
COPY admin-web-app/nginx.conf.template /etc/nginx/templates/default.conf.template
COPY admin-web-app/runtime-config.template.js /usr/share/nginx/html/runtime-config.template.js
COPY admin-web-app/docker-entrypoint.d/50-admin-ui-runtime-config.sh /docker-entrypoint.d/50-admin-ui-runtime-config.sh
COPY --from=build /app/dist /usr/share/nginx/html
RUN chmod 0755 /docker-entrypoint.d/50-admin-ui-runtime-config.sh
EXPOSE 8080
HEALTHCHECK --interval=2s --timeout=1s --start-period=1s --retries=10 \
    CMD ["wget", "-q", "-O", "-", "http://127.0.0.1:8080/health"]
