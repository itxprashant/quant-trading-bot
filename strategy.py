"""
Steady-profit strategy with micro-trend integration.

Two analysis layers:
  1. MACRO (every 5 cycles): RSI, Bollinger, EMA, minima/maxima from historical data
  2. MICRO (every cycle): 1-second price ticks, 6-second trends, velocity, spikes

Trading rules:
  - Spread capture as steady income
  - Strong macro signals (score ≥ 3) for directional trades
  - Micro spikes/surges for quick scalps when aligned with macro
  - Never guess — only trade when math is clear
"""

import logging
import statistics
import config
from datastore import DataStore
from microtrend import MicroTrend

log = logging.getLogger("strategy")

MAX_ORDER = 50
SOFT_LIMIT = 40


def ema(prices, period):
    if len(prices) < period:
        return statistics.mean(prices) if prices else 100
    k = 2 / (period + 1)
    r = prices[0]
    for p in prices[1:]:
        r = p * k + r * (1 - k)
    return r


def rsi(prices, period=14):
    if len(prices) < period + 1:
        return 50.0
    changes = [prices[i] - prices[i - 1] for i in range(1, len(prices))]
    recent = changes[-period:]
    avg_gain = sum(max(c, 0) for c in recent) / period
    avg_loss = sum(max(-c, 0) for c in recent) / period
    if avg_loss < 0.001:
        return 100.0
    return 100 - (100 / (1 + avg_gain / avg_loss))


def bollinger_bands(prices, period=20):
    if len(prices) < period:
        period = max(len(prices), 2)
    r = prices[-period:]
    m = statistics.mean(r)
    s = statistics.stdev(r) if len(r) > 1 else 0.1
    return m - 2 * s, m, m + 2 * s


def find_local_extrema(prices, window=5):
    minima, maxima = [], []
    for i in range(window, len(prices) - window):
        local = prices[i - window: i + window + 1]
        if prices[i] == min(local):
            minima.append(prices[i])
        if prices[i] == max(local):
            maxima.append(prices[i])
    return minima, maxima


class AdaptiveStrategy:
    def __init__(self, client):
        self.client = client
        self.db = DataStore()
        self.micro = MicroTrend(window=15)
        self.cycle = 0
        self._macro_cache = {}  # cached macro analysis

    def get_positions(self):
        portfolio = self.client.get_portfolio()
        positions = portfolio.get("positions", {})
        return portfolio.get("cash_balance", 0), positions

    def _poll_price(self, stock):
        """Quick price poll for micro-trend — just current price + orderbook top."""
        ob = self.client.get_orderbook(stock)
        bids = ob.get("bids", [])
        asks = ob.get("asks", [])
        if not bids or not asks:
            return None
        bid = bids[0]["price"]
        ask = asks[0]["price"]
        mid = (bid + ask) / 2

        bid_vol = sum(b["quantity"] for b in bids[:3])
        ask_vol = sum(a["quantity"] for a in asks[:3])

        # Record to both micro-tracker and SQLite
        self.micro.record(stock, mid, bid, ask)
        self.db.record_price(stock, mid, 0, bid, ask, bid_vol, ask_vol)

        return {"bid": bid, "ask": ask, "mid": mid, "spread": ask - bid,
                "bid_vol": bid_vol, "ask_vol": ask_vol}

    def _macro_analysis(self, stock):
        """Full macro analysis (expensive, do every few cycles)."""
        hist = self.client.get_price_history(stock, limit=100)
        api_prices = [h["price"] for h in hist]
        if len(api_prices) < 10:
            return None

        db_prices = self.db.get_price_array(stock, 500)
        prices = db_prices if len(db_prices) > len(api_prices) else api_prices

        rsi_val = rsi(prices, 14)
        bb_lo, bb_mid, bb_hi = bollinger_bands(prices, 20)
        ema5 = ema(prices, 5)
        ema20 = ema(prices, 20)
        pct = ((prices[-1] - min(prices)) / (max(prices) - min(prices)) * 100) if max(prices) != min(prices) else 50
        minima, maxima = find_local_extrema(prices, 5)

        return {
            "rsi": rsi_val, "bb_lo": bb_lo, "bb_mid": bb_mid, "bb_hi": bb_hi,
            "ema5": ema5, "ema20": ema20, "percentile": pct,
            "recent_min": minima[-1] if minima else min(prices),
            "recent_max": maxima[-1] if maxima else max(prices),
            "prices": prices,
        }

    def analyze_stock(self, stock):
        """Combined micro + macro analysis."""
        live = self._poll_price(stock)
        if not live:
            return None

        # Macro: refresh every 5 cycles
        if self.cycle % 5 == 0 or stock not in self._macro_cache:
            macro = self._macro_analysis(stock)
            if macro:
                self._macro_cache[stock] = macro

        macro = self._macro_cache.get(stock)
        micro = self.micro.analyze(stock)

        return {
            "stock": stock,
            "live": live,
            "macro": macro,
            "micro": micro,
        }

    def generate_orders(self, analysis, current_pos):
        stock = analysis["stock"]
        live = analysis["live"]
        macro = analysis["macro"]
        micro = analysis["micro"]

        bid, ask = live["bid"], live["ask"]
        spread = live["spread"]
        room_buy = 50 - current_pos
        room_sell = current_pos + 50

        # ── Log micro-trend sparkline ──
        sparkline = self.micro.format_sparkline(stock)
        if micro:
            log.info(
                "  %s $%.2f [%s] %s Δ6s=%+.2f(%.2f%%) v=%.3f a=%.3f c=%.1f %s",
                stock, live["mid"], sparkline, micro["micro_direction"],
                micro["delta_6s"], micro["pct_6s"],
                micro["velocity"], micro["acceleration"],
                micro["consistency"],
                "⚡SPIKE" if micro["sudden_move"] else "",
            )
        else:
            log.info("  %s $%.2f [collecting data...]", stock, live["mid"])

        if macro:
            log.info(
                "    RSI=%.0f BB[%.2f|%.2f] EMA5/20=%.2f/%.2f %%=%.0f",
                macro["rsi"], macro["bb_lo"], macro["bb_hi"],
                macro["ema5"], macro["ema20"], macro["percentile"],
            )

        # ─── Unwind ───
        if current_pos > SOFT_LIMIT:
            qty = min(MAX_ORDER, current_pos)
            log.info("    ⚠ UNWIND SELL x%d", qty)
            return [("sell", round(bid - 1.0, 2), qty)]
        if current_pos < -SOFT_LIMIT:
            qty = min(MAX_ORDER, -current_pos)
            log.info("    ⚠ UNWIND BUY x%d", qty)
            return [("buy", round(ask + 1.0, 2), qty)]

        # ─── Score macro signals ───
        buy_pts, sell_pts = 0, 0
        buy_why, sell_why = [], []

        if macro:
            if macro["rsi"] < 25:
                buy_pts += 2; buy_why.append(f"RSI{macro['rsi']:.0f}")
            elif macro["rsi"] < 35:
                buy_pts += 1; buy_why.append(f"RSI{macro['rsi']:.0f}")
            if macro["rsi"] > 75:
                sell_pts += 2; sell_why.append(f"RSI{macro['rsi']:.0f}")
            elif macro["rsi"] > 65:
                sell_pts += 1; sell_why.append(f"RSI{macro['rsi']:.0f}")

            if live["mid"] <= macro["bb_lo"]:
                buy_pts += 2; buy_why.append("BB↓")
            if live["mid"] >= macro["bb_hi"]:
                sell_pts += 2; sell_why.append("BB↑")

            if live["mid"] <= macro["recent_min"] * 1.003:
                buy_pts += 1; buy_why.append("MIN")
            if live["mid"] >= macro["recent_max"] * 0.997:
                sell_pts += 1; sell_why.append("MAX")

            if macro["ema5"] > macro["ema20"] * 1.002:
                buy_pts += 1; buy_why.append("EMA↑")
            elif macro["ema5"] < macro["ema20"] * 0.998:
                sell_pts += 1; sell_why.append("EMA↓")

            if macro["percentile"] < 10:
                buy_pts += 1; buy_why.append(f"%{macro['percentile']:.0f}")
            elif macro["percentile"] > 90:
                sell_pts += 1; sell_why.append(f"%{macro['percentile']:.0f}")

        # ─── Score micro signals (instant) ───
        if micro:
            # Sudden surge → scalp it
            if micro["micro_direction"] == "SURGE_UP" and micro["consistency"] > 0.5:
                buy_pts += 2; buy_why.append(f"SURGE↑{micro['pct_6s']:+.2f}%")
            elif micro["micro_direction"] == "SURGE_DOWN" and micro["consistency"] < -0.5:
                sell_pts += 2; sell_why.append(f"SURGE↓{micro['pct_6s']:+.2f}%")

            # Strong velocity
            if micro["velocity"] > 0.05:
                buy_pts += 1; buy_why.append(f"v+{micro['velocity']:.2f}")
            elif micro["velocity"] < -0.05:
                sell_pts += 1; sell_why.append(f"v{micro['velocity']:.2f}")

            # Spike detection — sudden move aligned with macro
            if micro["sudden_move"]:
                if micro["spike"] > 0:
                    buy_pts += 1; buy_why.append("SPIKE↑")
                else:
                    sell_pts += 1; sell_why.append("SPIKE↓")

        net = buy_pts - sell_pts

        # ═══ Trade on strong signals ═══
        if net >= 3 and sell_pts <= 1:
            qty = min(MAX_ORDER, room_buy)
            if qty > 0:
                price = round(ask + 0.05, 2)  # Marketable limit
                log.info("    🟢 BUY x%d @ $%.2f [%d: %s]", qty, price, buy_pts, "+".join(buy_why))
                return [("buy", price, qty)]

        if net <= -3 and buy_pts <= 1:
            qty = min(MAX_ORDER, room_sell)
            if qty > 0:
                price = round(bid - 0.05, 2)  # Marketable limit
                log.info("    🔴 SELL x%d @ $%.2f [%d: %s]", qty, price, sell_pts, "+".join(sell_why))
                return [("sell", price, qty)]

        # ═══ Spread capture ═══
        if spread >= 0.02:
            cap = min(MAX_ORDER, room_buy, room_sell)
            if cap > 0:
                skew = current_pos * config.INVENTORY_SKEW
                bp = round(bid + 0.01 - skew, 2)
                sp = round(ask - 0.01 - skew, 2)
                if sp > bp:
                    log.info("    📊 SPREAD x%d ($%.2f→$%.2f) skew=%.2f", cap, bp, sp, skew)
                    return [("buy", bp, cap), ("sell", sp, cap)]

        log.info("    · wait (b=%d s=%d)", buy_pts, sell_pts)
        return []

    def execute(self, stocks=None):
        if stocks is None:
            stocks = config.STOCKS
        self.cycle += 1

        cash, positions = self.get_positions()
        pnl = self.client.get_portfolio().get("pnl", 0)
        log.info("Cash: $%.2f | P&L: $%.2f | Pos: %s", cash, pnl, positions)

        all_orders = []
        for stock in stocks:
            pos = positions.get(stock, 0)
            try:
                analysis = self.analyze_stock(stock)
                if not analysis:
                    continue
                for side, price, qty in self.generate_orders(analysis, pos):
                    try:
                        result = self.client.place_order(stock, side, qty, price)
                        self.db.record_trade(stock, side, qty, price, result.get("id"), result.get("status"), pnl)
                        all_orders.append(result)
                    except Exception as e:
                        log.error("Failed %s %s: %s", side, stock, e)
            except Exception as e:
                log.error("%s error: %s", stock, e)
        return all_orders
