# The motion service of the Graphics lab (GFX-005): Remotion and headless Chrome behind a small
# HTTP server. The container runs with no internet, so everything it needs (the npm packages, the
# browser, the bundled compositions and the fonts) is put in at build time.
#
# Build context: this folder, plus the named context `fonts` (the backend's font folder, see
# docker-compose.yml), so the fonts are the same files the backend uses and are never copied
# into git a second time.
FROM node:24-bookworm-slim

# The system libraries Chrome Headless Shell needs (Remotion's list for Debian).
RUN apt-get update \
    && apt-get install --no-install-recommends -y \
        libnss3 libdbus-1-3 libatk1.0-0 libatk-bridge2.0-0 libgbm1 libasound2 libxrandr2 \
        libxkbcommon0 libxfixes3 libxcomposite1 libxdamage1 libpango-1.0-0 libcairo2 libcups2 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY package.json package-lock.json ./
RUN npm ci --omit=dev --no-audit --no-fund

COPY tsconfig.json ./
COPY scripts ./scripts
COPY src ./src
COPY --from=fonts Montserrat-ExtraBold.ttf Inter-Medium.ttf ./public/fonts/

# Bundles the compositions and downloads the browser (the one step that needs the internet).
RUN node scripts/bundle.ts

# A non-root user. The root filesystem is read-only when the container runs, so the browser and
# Remotion work in /tmp (a tmpfs).
RUN groupadd --gid 10002 motion \
    && useradd --uid 10002 --gid motion --no-create-home --shell /usr/sbin/nologin motion
USER motion
ENV HOME=/tmp \
    NODE_ENV=production \
    PORT=8090

EXPOSE 8090
CMD ["node", "src/server/index.ts"]
