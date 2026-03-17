"""
High-frequency micro-trend tracker.
Polls prices every ~1 second and maintains a rolling window for
instantaneous trend detection (last 5-6 seconds).
"""

import time
import logging
import statistics
from collections import deque

log = logging.getLogger("microtrend")


class MicroTrend:
    """
    Tracks per-second price ticks per stock.
    Maintains rolling windows for instant analysis.
    """

    def __init__(self, window=10):
        self.window = window  # seconds of history to keep in memory
        self.ticks = {}       # stock -> deque of (timestamp, price, bid, ask)

    def record(self, stock, price, bid, ask):
        if stock not in self.ticks:
            self.ticks[stock] = deque(maxlen=self.window * 5)  # ~5 ticks/sec max
        self.ticks[stock].append((time.time(), price, bid, ask))

    def get_recent(self, stock, seconds=6):
        """Get ticks from the last N seconds."""
        if stock not in self.ticks:
            return []
        cutoff = time.time() - seconds
        return [(t, p, b, a) for t, p, b, a in self.ticks[stock] if t >= cutoff]

    def analyze(self, stock):
        """
        Micro-trend analysis over the last 5-6 seconds.
        Returns dict with instant signals, or None if not enough data.
        """
        ticks_6s = self.get_recent(stock, 6)
        ticks_3s = self.get_recent(stock, 3)
        ticks_1s = self.get_recent(stock, 1)

        if len(ticks_6s) < 3:
            return None

        prices_6s = [p for _, p, _, _ in ticks_6s]
        prices_3s = [p for _, p, _, _ in ticks_3s] if ticks_3s else prices_6s[-3:]
        prices_1s = [p for _, p, _, _ in ticks_1s] if ticks_1s else [prices_6s[-1]]

        first_6s = prices_6s[0]
        last_6s = prices_6s[-1]
        delta_6s = last_6s - first_6s    # Total move in 6 seconds
        pct_6s = delta_6s / first_6s * 100 if first_6s else 0

        first_3s = prices_3s[0] if prices_3s else first_6s
        delta_3s = last_6s - first_3s
        pct_3s = delta_3s / first_3s * 100 if first_3s else 0

        # Velocity: price change per second
        elapsed = ticks_6s[-1][0] - ticks_6s[0][0]
        velocity = delta_6s / elapsed if elapsed > 0.5 else 0

        # Acceleration: is velocity increasing?
        if len(prices_6s) >= 4:
            mid_idx = len(prices_6s) // 2
            v1 = prices_6s[mid_idx] - prices_6s[0]
            v2 = prices_6s[-1] - prices_6s[mid_idx]
            acceleration = v2 - v1  # positive = speeding up
        else:
            acceleration = 0

        # Direction consistency: how many sequential ticks kept same direction?
        ups = 0
        downs = 0
        for i in range(1, len(prices_6s)):
            if prices_6s[i] > prices_6s[i - 1]:
                ups += 1
            elif prices_6s[i] < prices_6s[i - 1]:
                downs += 1
        total_moves = ups + downs
        consistency = (ups - downs) / total_moves if total_moves > 0 else 0

        # Micro volatility
        if len(prices_6s) > 1:
            micro_vol = statistics.stdev(prices_6s)
        else:
            micro_vol = 0

        # Sudden spike detection: last 1s vs previous avg
        avg_before = statistics.mean(prices_6s[:-max(1, len(prices_1s))]) if len(prices_6s) > len(prices_1s) else prices_6s[0]
        current = prices_6s[-1]
        spike = (current - avg_before) / avg_before * 100 if avg_before else 0
        sudden_move = abs(spike) > 0.15  # >0.15% in last second = sudden

        # Classify micro-trend
        if pct_6s > 0.1 and consistency > 0.3:
            micro_direction = "SURGE_UP"
        elif pct_6s < -0.1 and consistency < -0.3:
            micro_direction = "SURGE_DOWN"
        elif abs(pct_6s) < 0.05:
            micro_direction = "FLAT"
        elif pct_6s > 0:
            micro_direction = "DRIFT_UP"
        else:
            micro_direction = "DRIFT_DOWN"

        result = {
            "stock": stock,
            "ticks_count": len(ticks_6s),
            "current": current,
            "delta_6s": delta_6s,
            "pct_6s": pct_6s,
            "delta_3s": delta_3s,
            "pct_3s": pct_3s,
            "velocity": velocity,          # $/sec
            "acceleration": acceleration,  # $/sec acceleration
            "consistency": consistency,    # -1 to +1
            "micro_vol": micro_vol,
            "spike": spike,
            "sudden_move": sudden_move,
            "micro_direction": micro_direction,
            "prices_6s": prices_6s,
        }

        return result

    def format_sparkline(self, stock):
        """ASCII sparkline of last 6 seconds."""
        ticks = self.get_recent(stock, 6)
        if len(ticks) < 2:
            return "---"
        prices = [p for _, p, _, _ in ticks]
        lo, hi = min(prices), max(prices)
        rng = hi - lo
        if rng < 0.01:
            return "─" * min(len(prices), 20)
        chars = "▁▂▃▄▅▆▇█"
        line = ""
        for p in prices[-20:]:
            idx = int((p - lo) / rng * (len(chars) - 1))
            line += chars[min(idx, len(chars) - 1)]
        return line
