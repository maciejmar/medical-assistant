# syntax=docker/dockerfile:1.7
FROM node:20-alpine AS build
WORKDIR /app
COPY package.json package-lock.json* ./
RUN --mount=type=cache,target=/root/.npm npm install --no-audit --no-fund
COPY . .
RUN npx ng build --configuration production

FROM nginx:1.27-alpine AS runtime
RUN rm /etc/nginx/conf.d/default.conf
COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/dist/logoped-assist/browser /usr/share/nginx/html
EXPOSE 80
# 127.0.0.1, nie localhost: w obrazie alpine localhost rozwiązuje się do ::1 (IPv6), a nginx
# nasłuchuje tylko na IPv4 – test zdrowia zawodził, choć strona działała.
HEALTHCHECK --interval=30s --timeout=3s CMD wget -qO- http://127.0.0.1/ >/dev/null || exit 1
