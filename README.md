# 📈 Quant Trading Bot

An automated **market-making bot** for the [DevClub Quant Trading Simulation](https://quant.devclub.in). It continuously quotes buy and sell orders around the mid-price, skewing prices based on current inventory to manage risk and capture the spread.

Two interchangeable implementations are provided:

| Variant | Runtime | API Transport | Best For |
|---------|---------|---------------|----------|
| **`bot.js`** | Node.js + Puppeteer | Headless Chromium (bypasses Cloudflare TLS) | Production / Docker |
| **`bot.py`** | Python 3 | `requests` + `websocket-client` (forces IPv4) | Local development |

---

## 🏗️ Architecture

```
┌─────────────┐     REST / WS      ┌──────────────────────┐
│  bot.js     │◄──────────────────►│  quant.devclub.in    │
│  bot.py     │                    │  (Trading Platform)  │
├─────────────┤                    └──────────────────────┘
│  Strategy   │  ← Adaptive market-making with inventory skew
│  DataStore  │  ← SQLite price history cache
│  MicroTrend │  ← Real-time tick analysis (velocity, spikes)
└─────────────┘
```

### Key Modules

| File | Purpose |
|------|---------|
| `bot.js` | Node.js entry point — Puppeteer-based API client + market maker |
| `bot.py` | Python entry point — REST/WebSocket client + trading loop |
| `config.py` | Shared configuration (credentials, strategy params) |
| `api_client.py` | Python REST client with JWT management |
| `strategy.py` | Adaptive strategy: RSI, Bollinger Bands, EMA, local extrema |
| `datastore.py` | SQLite-backed price history store |
| `microtrend.py` | Short-window trend detection (velocity, spike detection) |

---

## ⚙️ Configuration

Edit `config.py` (Python bot) or the `CONFIG` object in `bot.js` to set:

| Parameter | Default | Description |
|-----------|---------|-------------|
| `username` / `password` | — | Platform login credentials |
| `stocks` | Pepsi, Coca-Cola, Fanta | Symbols to trade |
| `spread` | `$0.30` | Base bid-ask spread |
| `orderSize` | `5` (JS) / `50` (PY) | Quantity per order side |
| `inventorySkew` | `$0.02` / unit | Price offset per inventory unit |
| `refreshInterval` | `4s` (JS) / `0.2s` (PY) | Cycle interval |
| `maxPosition` | `±50` | Position limits per stock |

---

## 🐳 Docker

### Build

```bash
docker build -t quant-bot .
```

### Run the Node.js bot (default)

```bash
docker run --rm -it quant-bot
```

### Run the Python bot instead

```bash
docker run --rm -it quant-bot python3 bot.py
```

### Dry-run mode (no real orders)

```bash
# Node.js
docker run --rm -it quant-bot node bot.js --dry-run

# Python
docker run --rm -it quant-bot python3 bot.py --dry-run
```

### Override credentials at runtime

```bash
docker run --rm -it \
  -e BOT_USERNAME=myuser \
  -e BOT_PASSWORD=mypass \
  quant-bot
```

> **Note:** Environment-variable credential overrides require adding `os.environ.get()` calls in `config.py`. Currently, credentials are set directly in the config files.

---

## 🖥️ Local Setup (without Docker)

### Prerequisites

- **Node.js ≥ 18** and **npm**
- **Python ≥ 3.10**
- **Chromium** installed (for `bot.js`)

### Install dependencies

```bash
# Node
npm install

# Python
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### Run

```bash
# Node.js bot
node bot.js

# Python bot
python bot.py

# Dry-run
node bot.js --dry-run
python bot.py --dry-run
```

---

## 📊 Strategy Overview

The bot uses an **adaptive market-making** strategy with two analysis layers:

1. **Macro** (every 5 cycles) — RSI, Bollinger Bands, EMA crossover, local minima/maxima from historical prices.
2. **Micro** (every cycle) — 1-second tick analysis, 6-second trends, price velocity, and spike detection.

Orders are placed symmetrically around the mid-price, skewed by current inventory:
- **Long inventory** → lower bid/ask to encourage selling
- **Short inventory** → higher bid/ask to encourage buying

---

## 📜 License

ISC
