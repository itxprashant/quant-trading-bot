# ══════════════════════════════════════════════════════════════
#  Quant Trading Bot — Docker Image
#  Supports both bot.js (Node/Puppeteer) and bot.py (Python)
# ══════════════════════════════════════════════════════════════

FROM node:20-bookworm-slim

# ── System dependencies (Chromium for Puppeteer + Python 3) ──
RUN apt-get update && apt-get install -y --no-install-recommends \
        chromium \
        python3 \
        python3-pip \
        python3-venv \
        fonts-liberation \
        libatk-bridge2.0-0 \
        libatk1.0-0 \
        libcups2 \
        libdrm2 \
        libgbm1 \
        libnss3 \
        libxcomposite1 \
        libxdamage1 \
        libxrandr2 \
        libxss1 \
        ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Tell Puppeteer / bot.js where Chromium lives
ENV PUPPETEER_EXECUTABLE_PATH=/usr/bin/chromium
ENV CHROMIUM_PATH=/usr/bin/chromium

WORKDIR /app

# ── Node dependencies ────────────────────────────────────────
COPY package.json package-lock.json ./
RUN npm ci --omit=dev

# ── Python dependencies ──────────────────────────────────────
COPY requirements.txt ./
RUN pip3 install --no-cache-dir --break-system-packages -r requirements.txt

# ── Application code ─────────────────────────────────────────
COPY bot.js bot.py config.py api_client.py strategy.py \
     datastore.py microtrend.py ./

# ── Default: run the Node.js bot ─────────────────────────────
#  Override with:  docker run <image> python3 bot.py
CMD ["node", "bot.js"]
