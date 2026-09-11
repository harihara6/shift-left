# syntax=docker/dockerfile:1

# --- build: the production bundle (no identity switcher, no inline scripts) ---
FROM node:24-alpine AS build
WORKDIR /src
COPY package.json package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY . .
RUN npx ng build --configuration production

# --- runtime: static files and the /api proxy, as a non-root user ---
FROM nginxinc/nginx-unprivileged:1.27-alpine
COPY nginx/security-headers.conf /etc/nginx/snippets/security-headers.conf
COPY nginx.conf.template /etc/nginx/templates/default.conf.template
COPY --from=build /src/dist/frontend/browser /usr/share/nginx/html
# Where the backend answers, from inside the container network.
ENV BACKEND_URL=http://backend:8000
EXPOSE 8080
