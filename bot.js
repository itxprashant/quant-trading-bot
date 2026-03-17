#!/usr/bin/env node
/**
 * Quant Trading Bot — Market-Making with Inventory Skew
 * =====================================================
 * Uses Puppeteer to bypass Cloudflare TLS restrictions.
 * All API calls are routed through a headless Chrome browser.
 *
 * Usage:
 *   node bot.js              # Run the bot
 *   node bot.js --dry-run    # Show quotes without placing orders
 */

const puppeteer = require("puppeteer-core");

// ═══════════════════════════════════════════════════════════════
// Configuration
// ═══════════════════════════════════════════════════════════════
const CONFIG = {
    baseUrl: "https://quant.devclub.in/backend/api",
    wsUrl: "wss://quant.devclub.in/backend/ws",
    username: "B23",
    password: "7849",

    stocks: ["Pepsi", "Coca-Cola", "Fanta"],
    maxPosition: 50,
    minPosition: -50,

    // Strategy
    spread: 0.30,          // Base spread around mid-price ($)
    orderSize: 5,          // Default order quantity per side
    inventorySkew: 0.02,   // Price skew per unit of inventory ($)
    refreshInterval: 4000, // ms between strategy cycles
    chromePath: process.env.PUPPETEER_EXECUTABLE_PATH || "/usr/bin/chromium",
};

const DRY_RUN = process.argv.includes("--dry-run");

// ═══════════════════════════════════════════════════════════════
// API Client (all calls go through Puppeteer's page.evaluate)
// ═══════════════════════════════════════════════════════════════
class ApiClient {
    constructor() {
        this.browser = null;
        this.page = null;
        this.token = null;
    }

    async init() {
        this.browser = await puppeteer.launch({
            executablePath: CONFIG.chromePath,
            headless: true,
            args: ["--no-sandbox", "--disable-setuid-sandbox", "--disable-gpu"],
        });
        this.page = await this.browser.newPage();
        // Navigate to the site first so fetch calls share the same origin
        await this.page.goto("https://quant.devclub.in", { waitUntil: "domcontentloaded", timeout: 15000 });
        log("Browser initialized");
    }

    async close() {
        if (this.browser) await this.browser.close();
    }

    /** Execute a fetch call inside the browser context */
    async apiFetch(path, options = {}) {
        const url = `${CONFIG.baseUrl}${path}`;
        const token = this.token;
        return this.page.evaluate(
            async ({ url, options, token }) => {
                const headers = { ...(options.headers || {}) };
                if (token) headers["Authorization"] = `Bearer ${token}`;
                if (options.json) headers["Content-Type"] = "application/json";
                const resp = await fetch(url, {
                    method: options.method || "GET",
                    headers,
                    body: options.json ? JSON.stringify(options.json) : options.body,
                });
                const data = await resp.json();
                return { status: resp.status, data };
            },
            { url, options, token }
        );
    }

    async login() {
        const formBody = `username=${encodeURIComponent(CONFIG.username)}&password=${encodeURIComponent(CONFIG.password)}`;
        const result = await this.page.evaluate(
            async ({ url, formBody }) => {
                const resp = await fetch(url, {
                    method: "POST",
                    headers: { "Content-Type": "application/x-www-form-urlencoded" },
                    body: formBody,
                });
                return { status: resp.status, data: await resp.json() };
            },
            { url: `${CONFIG.baseUrl}/auth/login`, formBody }
        );

        if (result.status !== 200) throw new Error(`Login failed: ${JSON.stringify(result)}`);
        this.token = result.data.access_token;
        log(`Logged in as ${CONFIG.username}`);
        return this.token;
    }

    async getStocks() {
        return (await this.apiFetch("/market/stocks")).data;
    }

    async getPrice(stock) {
        return (await this.apiFetch(`/market/${encodeURIComponent(stock)}/current-price`)).data;
    }

    async getOrderbook(stock) {
        return (await this.apiFetch(`/market/${encodeURIComponent(stock)}/orderbook`)).data;
    }

    async getPortfolio() {
        return (await this.apiFetch("/portfolio")).data;
    }

    async placeOrder(stock, side, quantity, price) {
        const payload = {
            stock_symbol: stock,
            order_type: side,
            quantity: Math.floor(quantity),
            price: Math.round(price * 100) / 100,
        };
        const result = await this.apiFetch("/orders", { method: "POST", json: payload });
        log(
            `ORDER ${side.toUpperCase()} ${stock} x${quantity} @ $${price.toFixed(2)} → id=${result.data.id} status=${result.data.status}`
        );
        return result.data;
    }
}

// ═══════════════════════════════════════════════════════════════
// Market-Making Strategy
// ═══════════════════════════════════════════════════════════════
class MarketMaker {
    constructor(client) {
        this.client = client;
        this.spread = CONFIG.spread;
        this.orderSize = CONFIG.orderSize;
        this.skew = CONFIG.inventorySkew;
    }

    computeQuotes(stock, orderbook, currentPos) {
        const bids = orderbook.bids || [];
        const asks = orderbook.asks || [];
        let mid;

        if (bids.length > 0 && asks.length > 0) {
            const bestBid = parseFloat(bids[0].price);
            const bestAsk = parseFloat(asks[0].price);
            mid = (bestBid + bestAsk) / 2;
        } else if (bids.length > 0) {
            mid = parseFloat(bids[0].price) + this.spread / 2;
        } else if (asks.length > 0) {
            mid = parseFloat(asks[0].price) - this.spread / 2;
        } else {
            return []; // No market data, skip
        }

        // Skew based on inventory
        const inventoryOffset = currentPos * this.skew;
        const adjustedMid = mid - inventoryOffset;

        const buyPrice = Math.round((adjustedMid - this.spread / 2) * 100) / 100;
        const sellPrice = Math.round((adjustedMid + this.spread / 2) * 100) / 100;

        // Clamp order sizes to position limits
        const buyQty = Math.min(this.orderSize, CONFIG.maxPosition - currentPos);
        const sellQty = Math.min(this.orderSize, currentPos - CONFIG.minPosition);

        const orders = [];
        if (buyQty > 0) orders.push({ side: "buy", price: buyPrice, qty: buyQty });
        if (sellQty > 0) orders.push({ side: "sell", price: sellPrice, qty: sellQty });

        return orders;
    }

    async execute(stocks) {
        const portfolio = await this.client.getPortfolio();
        const cash = portfolio.cash_balance || 0;
        const positions = {};
        for (const pos of portfolio.positions || []) {
            positions[pos.stock_symbol] = pos.quantity || 0;
        }

        log(`Cash: $${cash.toFixed(2)} | Positions: ${JSON.stringify(positions)}`);

        const placed = [];
        for (const stock of stocks) {
            const currentPos = positions[stock] || 0;
            try {
                const orderbook = await this.client.getOrderbook(stock);
                const quotes = this.computeQuotes(stock, orderbook, currentPos);

                for (const q of quotes) {
                    if (DRY_RUN) {
                        log(`[DRY] Would ${q.side.toUpperCase()} ${stock} x${q.qty} @ $${q.price.toFixed(2)}`);
                    } else {
                        try {
                            const result = await this.client.placeOrder(stock, q.side, q.qty, q.price);
                            placed.push(result);
                        } catch (e) {
                            log(`Order failed ${q.side} ${stock}: ${e.message}`, "ERROR");
                        }
                    }
                }
            } catch (e) {
                log(`Orderbook failed for ${stock}: ${e.message}`, "WARN");
            }
        }
        return placed;
    }
}

// ═══════════════════════════════════════════════════════════════
// Bot Runner
// ═══════════════════════════════════════════════════════════════
function log(msg, level = "INFO") {
    const ts = new Date().toISOString().replace("T", " ").substring(0, 19);
    console.log(`${ts} [${level}] ${msg}`);
}

function printPortfolio(portfolio) {
    const cash = portfolio.cash_balance || 0;
    const pnl = portfolio.pnl || 0;
    const prices = portfolio.current_prices || {};

    log("═".repeat(60));
    log(`  PORTFOLIO  │  Cash: $${cash.toFixed(2)}  │  P&L: $${pnl.toFixed(2)}`);
    log("─".repeat(60));
    for (const pos of portfolio.positions || []) {
        const sym = pos.stock_symbol;
        const qty = pos.quantity || 0;
        const price = prices[sym] || "?";
        log(`  ${sym.padEnd(12)} │  ${(qty >= 0 ? "+" : "") + qty} shares  │  price: $${price}`);
    }
    log("═".repeat(60));
}

async function main() {
    log("═".repeat(60));
    log("  QUANT TRADING BOT — Market Maker");
    log(`  Stocks: ${CONFIG.stocks.join(", ")}`);
    log(`  Spread: $${CONFIG.spread.toFixed(2)}  |  Order Size: ${CONFIG.orderSize}`);
    log(`  Refresh: ${CONFIG.refreshInterval / 1000}s  |  Dry Run: ${DRY_RUN}`);
    log("═".repeat(60));

    const client = new ApiClient();
    await client.init();
    await client.login();

    const strategy = new MarketMaker(client);

    // Show initial portfolio
    const portfolio = await client.getPortfolio();
    printPortfolio(portfolio);

    let cycle = 0;
    let running = true;

    process.on("SIGINT", () => {
        log("Shutdown signal received...");
        running = false;
    });
    process.on("SIGTERM", () => {
        log("Shutdown signal received...");
        running = false;
    });

    while (running) {
        cycle++;
        log(`─── Cycle ${cycle} ───`);

        try {
            const orders = await strategy.execute(CONFIG.stocks);
            if (!DRY_RUN) log(`Placed ${orders.length} orders this cycle`);

            // Print portfolio every 5 cycles
            if (cycle % 5 === 0) {
                try {
                    const p = await client.getPortfolio();
                    printPortfolio(p);
                } catch (e) {
                    log(`Portfolio fetch failed: ${e.message}`, "WARN");
                }
            }
        } catch (e) {
            log(`Cycle ${cycle} error: ${e.message}`, "ERROR");
        }

        // Re-login every 20 cycles to refresh token
        if (cycle % 20 === 0) {
            try {
                await client.login();
            } catch (e) {
                log(`Re-login failed: ${e.message}`, "ERROR");
            }
        }

        await new Promise((r) => setTimeout(r, CONFIG.refreshInterval));
    }

    log("Shutting down...");
    await client.close();
    log("Bot stopped.");
}

main().catch((e) => {
    console.error("Fatal:", e);
    process.exit(1);
});
