FROM node:22-alpine AS deps
WORKDIR /app
COPY package.json package-lock.json* ./
COPY packages/contracts/package.json packages/contracts/
COPY services/extract/package.json services/extract/
COPY services/engine/package.json services/engine/
COPY apps/web/package.json apps/web/
RUN npm install --workspace=@q-agent/contracts --workspace=@q-agent/engine --include-workspace-root=false

FROM node:22-alpine AS build
WORKDIR /app
COPY --from=deps /app/node_modules ./node_modules
COPY --from=deps /app/packages/contracts/node_modules ./packages/contracts/node_modules
COPY --from=deps /app/services/engine/node_modules ./services/engine/node_modules
COPY package.json ./
COPY packages/contracts ./packages/contracts
COPY services/engine ./services/engine
RUN npm run build -w @q-agent/contracts && npm run build -w @q-agent/engine

FROM node:22-alpine AS runner
WORKDIR /app
ENV NODE_ENV=production
ENV PORT=4002
COPY --from=build /app/packages/contracts ./packages/contracts
COPY --from=build /app/services/engine ./services/engine
COPY --from=build /app/node_modules ./node_modules
WORKDIR /app/services/engine
EXPOSE 4002
CMD ["node", "dist/index.js"]
