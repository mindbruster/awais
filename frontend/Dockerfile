# --- builder: install deps + produce dist ---
FROM node:22-alpine AS builder

WORKDIR /build

# Install deps with cache-friendly layer
COPY package*.json ./
RUN npm ci

COPY . .

# Vite substitutes import.meta.env.* at BUILD time and throws the value into the
# JavaScript bundle. There is no runtime environment on a static SPA, so this
# cannot be a Railway service variable — it has to be a build argument, and
# changing it means rebuilding the image, not restarting the service.
#
#   docker-compose / single host : /api/v1        (nginx proxies to the backend)
#   Railway / split domains      : https://api.<your-domain>/api/v1
#
# Getting this wrong produces a frontend that loads perfectly and cannot reach
# the API, so it is worth checking in the built bundle before going live:
#   docker run --rm <image> grep -ro 'https://api[^"]*' /usr/share/nginx/html/assets | head
ARG VITE_API_BASE_URL=/api/v1
ENV VITE_API_BASE_URL=$VITE_API_BASE_URL
RUN npm run build

# --- runtime: nginx serving the SPA ---
FROM nginx:1.27-alpine

# Railway assigns a port per deploy and it is not 80. nginx has no native
# support for env vars in its config, so use the official image's envsubst
# templating: /etc/nginx/templates/*.template are rendered into
# /etc/nginx/conf.d/ by the entrypoint before nginx starts.
#
# NGINX_ENVSUBST_FILTER pins substitution to PORT alone. Without it envsubst
# would also try to expand nginx's own runtime variables ($uri, $host) and
# silently blank them out.
ENV PORT=8080 \
    NGINX_ENVSUBST_FILTER=PORT

# NOTE: this deliberately does NOT reuse ../nginx.conf. That file proxies /api
# to a host literally named `backend`, which exists in docker-compose and
# nowhere else — on Railway the two services have separate public domains and
# nginx would refuse to start with "host not found in upstream: backend".
# docker-compose.prod.yml keeps using nginx.conf; this image is standalone.
RUN rm -f /etc/nginx/conf.d/default.conf && mkdir -p /etc/nginx/templates
COPY <<'NGINXCONF' /etc/nginx/templates/default.conf.template
server {
    listen ${PORT};
    server_name _;
    root /usr/share/nginx/html;
    index index.html;
    server_tokens off;

    gzip on;
    gzip_types text/css application/javascript application/json image/svg+xml;
    gzip_min_length 1024;

    # Hashed filenames — safe to cache forever.
    location /assets/ {
        access_log off;
        expires 1y;
        add_header Cache-Control "public, immutable";
    }

    # Never cache the shell: it is what points at the current asset hashes, and
    # a stale one serves a deploy whose assets no longer exist.
    location = /index.html {
        add_header Cache-Control "no-store";
    }

    # Railway healthcheck target. A static route, so it cannot be swallowed by
    # the SPA fallback below and reported healthy when the build is broken.
    location = /healthz {
        access_log off;
        default_type text/plain;
        return 200 "ok";
    }

    # SPA fallback — client-side routes are not files on disk.
    location / {
        try_files $uri $uri/ /index.html;
    }
}
NGINXCONF

COPY --from=builder /build/dist /usr/share/nginx/html

# Run as the image's own unprivileged `nginx` user. The master process normally
# stays root only to bind port 80; PORT here is >1024, so it does not need to.
# The entrypoint and nginx itself write to these paths, hence the chown.
RUN chown -R nginx:nginx /usr/share/nginx/html /var/cache/nginx /etc/nginx/conf.d && \
    touch /var/run/nginx.pid && chown nginx:nginx /var/run/nginx.pid
USER nginx

EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=3s --retries=3 \
    CMD wget -q --spider "http://127.0.0.1:${PORT}/healthz" || exit 1
