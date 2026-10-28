# The web app (Next.js), for `make demo` (M11). The hosted demo builds it on Vercel instead.
# Built from the repository root (pnpm workspace):
#   docker build -f apps/web/Dockerfile -t brimline-web .
FROM node:24.18.0-slim

ENV NEXT_TELEMETRY_DISABLED=1
RUN corepack enable
WORKDIR /app
COPY package.json pnpm-lock.yaml pnpm-workspace.yaml .npmrc* ./
COPY apps/web/package.json apps/web/
RUN pnpm install --frozen-lockfile --filter @brimline/web...

COPY apps/web/ apps/web/
RUN pnpm --filter @brimline/web build

USER node
WORKDIR /app/apps/web
EXPOSE 3000
CMD ["node_modules/.bin/next", "start", "--port", "3000"]
