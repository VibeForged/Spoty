FROM python:3.12-slim

# System deps:
#   ffmpeg                 - FFmpeg audio backend / fallback
#   openjdk-17-jre-headless- run bundled Lavalink (Lavalink 4 needs Java 17+)
#   nodejs (20, NodeSource)- run the browserless PO-token refresher sidecar
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        ffmpeg \
        openjdk-17-jre-headless \
        curl ca-certificates gnupg && \
    curl -fsSL https://deb.nodesource.com/setup_20.x | bash - && \
    apt-get install -y --no-install-recommends nodejs && \
    apt-get purge -y curl gnupg && apt-get autoremove -y && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Python deps
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Node deps for the PO-token refresher (installed before app copy for layer caching)
COPY package.json package-lock.json ./
RUN npm ci --omit=dev --no-audit --no-fund

COPY . .

RUN mkdir -p data logs

# Run Lavalink + the PO-token sidecar + the bot in one container via the launcher.
# The launcher resolves these paths/binaries from the environment.
ENV SPOTY_JAVA_BIN=/usr/bin/java \
    SPOTY_LAVALINK_DIR=/app/LavaLink \
    SPOTY_USER_DIR=/app/data

CMD ["python", "launcher.py"]
