# syntax=docker/dockerfile:1
FROM node:22-alpine AS deps
WORKDIR /app
COPY package.json package-lock.json ./
# Optional: behind a TLS-intercepting proxy pass its CA with  --secret id=ca_bundle,src=/path/ca.crt
RUN --mount=type=secret,id=ca_bundle,required=false,mode=0444 \
    sh -c 'if [ -f /run/secrets/ca_bundle ]; then export NODE_EXTRA_CA_CERTS=/run/secrets/ca_bundle; fi; npm ci --no-audit --no-fund'

FROM node:22-alpine AS build
WORKDIR /app
ENV NEXT_TELEMETRY_DISABLED=1
COPY --from=deps /app/node_modules ./node_modules
COPY . .
RUN npx next build

FROM node:22-alpine AS run
WORKDIR /app
ENV NODE_ENV=production NEXT_TELEMETRY_DISABLED=1 PORT=3000 HOSTNAME=0.0.0.0
RUN adduser -D -u 10001 web
COPY --from=build /app/.next/standalone ./
COPY --from=build /app/.next/static ./.next/static
USER web
EXPOSE 3000
CMD ["node", "server.js"]
