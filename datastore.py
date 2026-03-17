"""
Persistent price data store using SQLite.
Records every price tick and orderbook snapshot for historical analysis.
"""

import sqlite3
import time
import logging
import os

log = logging.getLogger("datastore")

DB_PATH = os.path.join(os.path.dirname(__file__), "market_data.sqlite3")


class DataStore:
    def __init__(self, db_path=DB_PATH):
        self.db_path = db_path
        self.conn = sqlite3.connect(db_path)
        self.conn.execute("PRAGMA journal_mode=WAL")
        self._create_tables()
        log.info("DataStore initialized at %s", db_path)

    def _create_tables(self):
        self.conn.executescript("""
            CREATE TABLE IF NOT EXISTS prices (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                stock TEXT NOT NULL,
                price REAL NOT NULL,
                price_change REAL,
                bid REAL,
                ask REAL,
                spread REAL,
                bid_volume INTEGER,
                ask_volume INTEGER,
                imbalance REAL,
                timestamp REAL NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_prices_stock_ts ON prices(stock, timestamp);

            CREATE TABLE IF NOT EXISTS trades (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                stock TEXT NOT NULL,
                side TEXT NOT NULL,
                quantity INTEGER NOT NULL,
                price REAL NOT NULL,
                order_id INTEGER,
                status TEXT,
                pnl_at_trade REAL,
                timestamp REAL NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_trades_stock ON trades(stock, timestamp);
        """)
        self.conn.commit()

    def record_price(self, stock, price, price_change, bid, ask, bid_vol, ask_vol):
        spread = ask - bid if ask and bid else 0
        total = bid_vol + ask_vol if bid_vol and ask_vol else 1
        imbalance = (bid_vol - ask_vol) / total if total > 0 else 0
        self.conn.execute(
            "INSERT INTO prices (stock, price, price_change, bid, ask, spread, bid_volume, ask_volume, imbalance, timestamp) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (stock, price, price_change, bid, ask, spread, bid_vol, ask_vol, imbalance, time.time()),
        )
        self.conn.commit()

    def record_trade(self, stock, side, qty, price, order_id, status, pnl):
        self.conn.execute(
            "INSERT INTO trades (stock, side, quantity, price, order_id, status, pnl_at_trade, timestamp) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (stock, side, qty, price, order_id, status, pnl, time.time()),
        )
        self.conn.commit()

    def get_prices(self, stock, limit=500):
        """Get recent prices for a stock."""
        cur = self.conn.execute(
            "SELECT price, price_change, bid, ask, spread, imbalance, timestamp FROM prices WHERE stock=? ORDER BY timestamp DESC LIMIT ?",
            (stock, limit),
        )
        rows = cur.fetchall()
        rows.reverse()  # chronological order
        return rows

    def get_price_array(self, stock, limit=500):
        """Get just the price values as a list."""
        rows = self.get_prices(stock, limit)
        return [r[0] for r in rows]

    def get_stats(self, stock, window=100):
        """Get rolling statistics for a stock."""
        prices = self.get_price_array(stock, window)
        if len(prices) < 10:
            return None
        import statistics
        return {
            "count": len(prices),
            "mean": statistics.mean(prices),
            "stdev": statistics.stdev(prices),
            "min": min(prices),
            "max": max(prices),
            "current": prices[-1],
            "range": max(prices) - min(prices),
        }

    def count_prices(self, stock):
        cur = self.conn.execute("SELECT COUNT(*) FROM prices WHERE stock=?", (stock,))
        return cur.fetchone()[0]

    def close(self):
        self.conn.close()
