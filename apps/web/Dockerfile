# syntax=docker/dockerfile:1
FROM node:22-alpine AS deps
WORKDIR /app
COPY package.json package-lock.json ./
COPY packages/contracts/package.json packages/contracts/
COPY apps/web/package.json apps/web/
COPY packages/contracts/tsconfig.json packages/contracts/
COPY packages/contracts/src packages/contracts/src
RUN npm ci

FROM node:22-alpine AS builder
WORKDIR /app
COPY --from=deps /app/node_modules ./node_modules
COPY package.json package-lock.json ./
COPY packages ./packages
COPY apps/web ./apps/web

ARG NEXT_PUBLIC_REALTIME_WS_URL=ws://localhost:8765/v1/realtime
ENV NEXT_PUBLIC_REALTIME_WS_URL=$NEXT_PUBLIC_REALTIME_WS_URL
ENV NEXT_TELEMETRY_DISABLED=1

RUN npm run build -w @q-agent/contracts \
  && npm run build -w @q-agent/web

FROM node:22-alpine AS runner
WORKDIR /app
ENV NODE_ENV=production
ENV NEXT_TELEMETRY_DISABLED=1
ENV PORT=3000
ENV HOSTNAME=0.0.0.0

RUN addgroup --system --gid 1001 nodejs \
  && adduser --system --uid 1001 nextjs
COPY --from=builder --chown=nextjs:nodejs /app/apps/web/.next/standalone ./
COPY --from=builder --chown=nextjs:nodejs /app/apps/web/.next/static ./apps/web/.next/static
COPY --from=builder --chown=nextjs:nodejs /app/apps/web/public ./apps/web/public

USER nextjs
EXPOSE 3000
CMD ["node", "apps/web/server.js"]
