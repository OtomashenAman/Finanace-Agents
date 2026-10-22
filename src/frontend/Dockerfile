# syntax=docker/dockerfile:1.7
# Frontend image: Vite + React
#   target "dev"     -> Vite dev server with HMR, source bind-mounted by compose
#   target "runtime" -> production: static build served by unprivileged nginx (default)

ARG NODE_VERSION=22
ARG NGINX_VERSION=1.27

# ---------------------------------------------------------------- deps
FROM node:${NODE_VERSION}-alpine AS deps
WORKDIR /app
COPY package.json package-lock.json ./
RUN --mount=type=cache,target=/root/.npm npm ci

# ---------------------------------------------------------------- dev
FROM deps AS dev
COPY . .
EXPOSE 8081
CMD ["npm", "run", "dev", "--", "--host", "0.0.0.0", "--port", "8081"]

# ---------------------------------------------------------------- build
FROM deps AS build
COPY . .
# Build-time API base (default: same-origin /api, proxied by nginx)
ARG VITE_API_BASE_URL=/api
ENV VITE_API_BASE_URL=${VITE_API_BASE_URL}
RUN npm run build

# ---------------------------------------------------------------- runtime
FROM nginxinc/nginx-unprivileged:${NGINX_VERSION}-alpine AS runtime

COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/dist /usr/share/nginx/html

EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD wget -qO- http://127.0.0.1:8080/healthz || exit 1
