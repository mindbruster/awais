# --- builder: install deps + produce dist ---
FROM node:22-alpine AS builder

WORKDIR /build

# Install deps with cache-friendly layer
COPY package*.json ./
RUN npm ci

# Build
COPY . .
ARG VITE_API_BASE_URL=/api/v1
ENV VITE_API_BASE_URL=$VITE_API_BASE_URL
RUN npm run build

# --- runtime: nginx serving the SPA ---
FROM nginx:1.27-alpine

# SPA + API reverse proxy config
COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=builder /build/dist /usr/share/nginx/html

EXPOSE 80

HEALTHCHECK --interval=30s --timeout=3s --retries=3 \
    CMD wget -q --spider http://127.0.0.1/ || exit 1
