FROM oven/bun:1.4.2-alpine AS build
WORKDIR /app
COPY services/control-panel/ui/package.json services/control-panel/ui/bun.lock ./
RUN bun install --frozen-lockfile
COPY services/control-panel/ui/components.json services/control-panel/ui/index.html services/control-panel/ui/tsconfig.json services/control-panel/ui/vite.config.ts ./
COPY services/control-panel/ui/src ./src
COPY services/control-panel/ui/public ./public
RUN bun run build

FROM nginx:1.28-alpine
COPY services/control-panel/ui/nginx.conf.template /etc/nginx/templates/default.conf.template
COPY --from=build /app/dist /usr/share/nginx/html
EXPOSE 8080
HEALTHCHECK --interval=2s --timeout=1s --start-period=1s --retries=10 \
    CMD ["wget", "-q", "-O", "-", "http://127.0.0.1:8080/health"]
