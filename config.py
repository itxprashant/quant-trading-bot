"""Configuration for the Quant Trading Bot."""

BASE_URL = "https://quant.devclub.in/backend/api"
WS_URL = "wss://quant.devclub.in/backend/ws"

USERNAME = ""
PASSWORD = ""

STOCKS = ["Pepsi", "Coca-Cola", "Fanta"]

# Position limits per stock (platform enforced ±50)
MAX_POSITION = 50
MIN_POSITION = -50

# Strategy parameters
SPREAD = 0.30          # Base spread around mid-price ($)
ORDER_SIZE = 50        # Default order quantity per side
INVENTORY_SKEW = 0.02  # Price skew per unit of inventory ($)
REFRESH_INTERVAL = 0.2 # Seconds between strategy re-evaluations
MAX_OPEN_ORDERS = 10   # Max open orders per stock (5 buy + 5 sell)

# Logging
LOG_LEVEL = "INFO"
LOG_FORMAT = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
