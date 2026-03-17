"""REST API client for the Quant Trading Platform.
Forces IPv4 connections to bypass Cloudflare IPv6 TLS issues.
"""

import time
import socket
import logging
import requests
from urllib3.util.connection import allowed_gai_family

import config

log = logging.getLogger("api_client")

# Force IPv4 globally — Cloudflare drops IPv6 TLS for this server
_orig_gai_family = allowed_gai_family


def _forced_ipv4():
    return socket.AF_INET


import urllib3.util.connection
urllib3.util.connection.allowed_gai_family = _forced_ipv4


class QuantClient:
    """Wraps all REST endpoints with automatic JWT management."""

    def __init__(self):
        self.base = config.BASE_URL
        self.token = None
        self.token_expiry = 0
        self.session = requests.Session()

    def _headers(self):
        if not self.token or time.time() > self.token_expiry - 60:
            self.login()
        return {"Authorization": f"Bearer {self.token}"}

    def login(self):
        resp = self.session.post(
            f"{self.base}/auth/login",
            data={"username": config.USERNAME, "password": config.PASSWORD},
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        resp.raise_for_status()
        data = resp.json()
        self.token = data["access_token"]
        self.token_expiry = time.time() + 25 * 60
        log.info("Logged in as %s", config.USERNAME)
        return self.token

    def get_stocks(self):
        resp = self.session.get(f"{self.base}/market/stocks", headers=self._headers())
        resp.raise_for_status()
        return resp.json()

    def get_price(self, stock):
        resp = self.session.get(
            f"{self.base}/market/{stock}/current-price", headers=self._headers()
        )
        resp.raise_for_status()
        return resp.json()

    def get_price_history(self, stock, limit=200):
        resp = self.session.get(
            f"{self.base}/market/{stock}/price-history",
            params={"limit": limit},
            headers=self._headers(),
        )
        resp.raise_for_status()
        return resp.json()

    def get_orderbook(self, stock):
        resp = self.session.get(
            f"{self.base}/market/{stock}/orderbook", headers=self._headers()
        )
        resp.raise_for_status()
        return resp.json()

    def get_portfolio(self):
        resp = self.session.get(f"{self.base}/portfolio", headers=self._headers())
        resp.raise_for_status()
        return resp.json()

    def place_order(self, stock, side, quantity, price):
        payload = {
            "stock_symbol": stock,
            "order_type": side,
            "quantity": int(quantity),
            "price": round(float(price), 2),
        }
        resp = self.session.post(
            f"{self.base}/orders", json=payload, headers=self._headers()
        )
        resp.raise_for_status()
        result = resp.json()
        log.info(
            "ORDER %s %s x%d @ $%.2f → id=%s status=%s",
            side.upper(),
            stock,
            quantity,
            price,
            result.get("id"),
            result.get("status"),
        )
        return result
