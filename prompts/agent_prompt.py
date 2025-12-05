import os

from dotenv import load_dotenv

load_dotenv()
import json
import os
import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional

# Add project root directory to Python path
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, project_root)
from integrations.kis_settings import is_kis_broker, is_websocket_enabled
from tools.general_tools import get_config_value
from tools.price_tools import (all_nasdaq_100_symbols, all_sse_50_symbols,
                               format_price_dict_with_names, get_open_prices,
                               get_today_init_position, get_yesterday_date,
                               get_yesterday_open_and_close_price,
                               get_yesterday_profit)

STOP_SIGNAL = "<FINISH_SIGNAL>"

agent_system_prompt = """
You are a stock fundamental analysis trading assistant.

Your goals are:
- Think and reason by calling available tools.
- You need to think about the prices of various stocks and their returns.
- Your long-term goal is to maximize returns through this portfolio.
- Before making decisions, gather as much information as possible through search tools to aid decision-making.

Thinking standards:
- Clearly show key intermediate steps:
  - Read input of yesterday's positions and today's prices
  - Update valuation and adjust weights for each target (if strategy requires)

Notes:
- You don't need to request user permission during operations, you can execute directly
- You must execute operations by calling tools, directly output operations will not be accepted

Here is the information you need:

Current time:
{date}

Your current positions (numbers after stock codes represent how many shares you hold, numbers after CASH represent your available cash):
{positions}

The current value represented by the stocks you hold:
{yesterday_close_price}

Current buying prices:
{today_buy_price}

When you think your task is complete, output
{STOP_SIGNAL}
"""

# KIS broker mode system prompt addon (with placeholder for quote source)
agent_system_prompt_kis_addon = """

## Broker Information
- Broker: Korea Investment & Securities (KIS) Paper Trading
- Order Type: Limit orders only (market orders not supported)
- Quotes: {quote_source}

## Order Guidelines
- You MUST specify the limit_price parameter when calling buy/sell.
- Query the current price first, then calculate an appropriate limit price.
- Example: current_price * 1.01 (buy), current_price * 0.99 (sell)

## Trading Hours
- US Stocks: 09:30-16:00 ET (23:30-06:00 KST, daylight saving time applies)
- Orders placed outside trading hours may not be executed.

## Order Examples
1. Buy 10 shares of AAPL (assuming current price $150)
   - Call get_price_local("AAPL", "2025-12-05")
   - After confirming the price, call buy("AAPL", 10, 151.50)

2. Sell 5 shares of MSFT from holdings
   - Call get_position() to check holdings
   - Call get_price_local("MSFT", "2025-12-05")
   - Call sell("MSFT", 5, 420.00)
"""


def get_agent_system_prompt(
    today_date: str, signature: str, market: str = "us", stock_symbols: Optional[List[str]] = None
) -> str:
    print(f"signature: {signature}")
    print(f"today_date: {today_date}")
    print(f"market: {market}")

    # Auto-select stock symbols based on market if not provided
    if stock_symbols is None:
        stock_symbols = all_sse_50_symbols if market == "cn" else all_nasdaq_100_symbols

    # Get yesterday's buy and sell prices
    yesterday_buy_prices, yesterday_sell_prices = get_yesterday_open_and_close_price(
        today_date, stock_symbols, market=market
    )
    today_buy_price = get_open_prices(today_date, stock_symbols, market=market)
    today_init_position = get_today_init_position(today_date, signature)
    # yesterday_profit = get_yesterday_profit(today_date, yesterday_buy_prices, yesterday_sell_prices, today_init_position)

    base_prompt = agent_system_prompt.format(
        date=today_date,
        positions=today_init_position,
        STOP_SIGNAL=STOP_SIGNAL,
        yesterday_close_price=yesterday_sell_prices,
        today_buy_price=today_buy_price,
        # yesterday_profit=yesterday_profit
    )

    # Include KIS broker mode addon when in KIS mode
    if is_kis_broker():
        # Determine quote source based on WebSocket mode
        if is_websocket_enabled():
            quote_source = "KIS WebSocket real-time (with REST fallback)"
        else:
            quote_source = "KIS REST API"
        kis_addon = agent_system_prompt_kis_addon.format(quote_source=quote_source)
        return base_prompt + kis_addon

    return base_prompt


if __name__ == "__main__":
    today_date = get_config_value("TODAY_DATE")
    signature = get_config_value("SIGNATURE")
    if signature is None:
        raise ValueError("SIGNATURE environment variable is not set")
    print(get_agent_system_prompt(today_date, signature))
