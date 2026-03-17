#!/usr/bin/env python3
"""
Quant Trading Bot — Market-Making with Inventory Skew
=====================================================
Connects to the DevClub Quant Trading Simulation via REST + WebSocket
and runs a market-making strategy on all available stocks.

Usage:
    python bot.py              # Run the bot
    python bot.py --dry-run    # Show what orders would be placed, don't execute
"""

import sys
import json
import time
import socket
import signal
import logging
import threading
import argparse

import websocket

import config
from api_client import QuantClient
from strategy import AdaptiveStrategy

logging.basicConfig(level=config.LOG_LEVEL, format=config.LOG_FORMAT)
log = logging.getLogger("bot")

shutdown = threading.Event()


def on_shutdown(signum, frame):
    log.info("Shutdown signal received, stopping...")
    shutdown.set()


signal.signal(signal.SIGINT, on_shutdown)
signal.signal(signal.SIGTERM, on_shutdown)


# Force IPv4 for websocket-client as well
_orig_create_connection = websocket._http.HAVE_CONTEXTVAR = False
_orig_socket_create = socket.create_connection


def _ipv4_create_connection(address, *args, **kwargs):
    host, port = address
    # Resolve to IPv4 only
    for res in socket.getaddrinfo(host, port, socket.AF_INET, socket.SOCK_STREAM):
        af, socktype, proto, canonname, sa = res
        try:
            return _orig_socket_create(sa, *args, **kwargs)
        except socket.error:
            continue
    return _orig_socket_create(address, *args, **kwargs)


socket.create_connection = _ipv4_create_connection


class TradingBot:
    def __init__(self, dry_run=False):
        self.client = QuantClient()
        self.strategy = AdaptiveStrategy(self.client)
        self.dry_run = dry_run
        self.ws = None
        self.ws_thread = None

    def print_portfolio(self):
        portfolio = self.client.get_portfolio()
        cash = portfolio.get("cash_balance", 0)
        pnl = portfolio.get("pnl", 0)
        positions = portfolio.get("positions", [])
        current_prices = portfolio.get("current_prices", {})

        log.info("═" * 60)
        log.info("  PORTFOLIO  │  Cash: $%.2f  │  P&L: $%.2f", cash, pnl)
        log.info("─" * 60)
        for sym, qty in positions.items():
            cur_price = current_prices.get(sym, "?")
            log.info("  %-12s │  %+4d shares  │  price: $%s", sym, qty, cur_price)
        log.info("═" * 60)

    def start_websocket(self):
        token = self.client.token or self.client.login()
        ws_url = f"{config.WS_URL}?token={token}"

        def on_message(ws, message):
            try:
                data = json.loads(message)
                msg_type = data.get("type", "unknown")
                if msg_type == "price_update":
                    log.debug("WS price: %s", data)
                elif msg_type in ("order_update", "trade"):
                    log.info("WS %s: %s", msg_type, data)
                else:
                    log.debug("WS: %s", data)
            except json.JSONDecodeError:
                log.debug("WS raw: %s", message)

        def on_error(ws, error):
            log.warning("WS error: %s", error)

        def on_close(ws, close_status, close_msg):
            log.info("WS closed: %s %s", close_status, close_msg)

        def on_open(ws):
            log.info("WebSocket connected")

        self.ws = websocket.WebSocketApp(
            ws_url,
            on_message=on_message,
            on_error=on_error,
            on_close=on_close,
            on_open=on_open,
        )
        self.ws_thread = threading.Thread(
            target=self.ws.run_forever, daemon=True, name="ws"
        )
        self.ws_thread.start()

    def run(self):
        log.info("=" * 60)
        log.info("  QUANT TRADING BOT — Market Maker")
        log.info("  Stocks: %s", ", ".join(config.STOCKS))
        log.info("  Spread: $%.2f  |  Order Size: %d", config.SPREAD, config.ORDER_SIZE)
        log.info("  Refresh: %ds  |  Dry Run: %s", config.REFRESH_INTERVAL, self.dry_run)
        log.info("=" * 60)

        self.client.login()
        self.print_portfolio()

        if not self.dry_run:
            try:
                self.start_websocket()
            except Exception as e:
                log.warning("WebSocket unavailable, using REST polling: %s", e)

        cycle = 0
        while not shutdown.is_set():
            cycle += 1
            log.info("─── Cycle %d ───", cycle)

            try:
                if self.dry_run:
                    self._dry_run_cycle()
                else:
                    orders = self.strategy.execute()
                    log.info("Placed %d orders this cycle", len(orders))

                if cycle % 5 == 0:
                    self.print_portfolio()

                # Re-login every 50 cycles to refresh token
                if cycle % 50 == 0:
                    self.client.login()

            except Exception as e:
                log.error("Cycle %d error: %s", cycle, e)

            shutdown.wait(timeout=config.REFRESH_INTERVAL)

        log.info("Bot stopped.")

    def _dry_run_cycle(self):
        cash, positions = self.strategy.get_positions()
        for stock in config.STOCKS:
            current_pos = positions.get(stock, 0)
            try:
                signals = self.strategy.analyze_stock(stock)
                if signals is None:
                    continue
                orders = self.strategy.generate_orders(signals, current_pos)
                for side, price, qty in orders:
                    log.info(
                        "[DRY] Would %s %s x%d @ $%.2f", side.upper(), stock, qty, price
                    )
            except Exception as e:
                log.warning("[DRY] %s error: %s", stock, e)


import getpass

def main():
    parser = argparse.ArgumentParser(description="Quant Trading Bot")
    parser.add_argument("--dry-run", action="store_true", help="Simulate without placing orders")
    args = parser.parse_args()

    if not config.USERNAME:
        config.USERNAME = input("Username: ")
    if not config.PASSWORD:
        config.PASSWORD = getpass.getpass("Password: ")

    bot = TradingBot(dry_run=args.dry_run)
    bot.run()


if __name__ == "__main__":
    main()
