FROM oven/bun:1.4.2-alpine AS build
WORKDIR /app
COPY admin-web-app/package.json admin-web-app/bun.lock ./
RUN bun install --frozen-lockfile
COPY admin-web-app/components.json admin-web-app/index.html admin-web-app/tsconfig.json admin-web-app/vite.config.ts ./
COPY admin-web-app/src ./src
COPY admin-web-app/public ./public
RUN bun run build

FROM nginx:1.28-alpine
COPY admin-web-app/nginx.conf.template /etc/nginx/templates/default.conf.template
COPY --from=build /app/dist /usr/share/nginx/html
EXPOSE 8080
HEALTHCHECK --interval=2s --timeout=1s --start-period=1s --retries=10 \
    CMD ["wget", "-q", "-O", "-", "http://127.0.0.1:8080/health"]
