FROM node:24-alpine AS deps
WORKDIR /app
# Everything runs as the unprivileged "node" user, which also owns node_modules so Vite can
# write its cache inside the container.
RUN chown node:node /app
USER node
COPY --chown=node:node package.json package-lock.json ./
RUN npm ci --no-audit --no-fund

# ---- development: Vite dev server, source bind-mounted by docker compose ----
FROM deps AS dev
COPY --chown=node:node . .
EXPOSE 5173
CMD ["npx", "vite", "--host", "0.0.0.0"]

# ---- build ----
FROM deps AS build
COPY --chown=node:node . .
RUN npm run build

# ---- production: static files on unprivileged nginx with strict security headers ----
FROM nginxinc/nginx-unprivileged:1.29-alpine AS prod
COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/dist /usr/share/nginx/html
EXPOSE 8080
