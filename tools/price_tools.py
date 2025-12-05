"""Price and position utilities for trading agents.

This module provides functions for:
- Stock symbol lists (NASDAQ 100, SSE 50)
- Price data retrieval (open prices, yesterday prices)
- Position management (read, write, sync)
- Trading day validation
- Log consistency validation
"""

import json
import os
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from tools.general_tools import get_config_value

# Project root directory
project_root = Path(__file__).resolve().parents[1]

# =============================================================================
# Stock Symbol Lists
# =============================================================================

all_nasdaq_100_symbols = [
    "NVDA", "MSFT", "AAPL", "GOOG", "GOOGL", "AMZN", "META", "AVGO", "TSLA",
    "NFLX", "PLTR", "COST", "ASML", "AMD", "CSCO", "AZN", "TMUS", "MU", "LIN",
    "PEP", "SHOP", "APP", "INTU", "AMAT", "LRCX", "PDD", "QCOM", "ARM", "INTC",
    "BKNG", "AMGN", "TXN", "ISRG", "GILD", "KLAC", "PANW", "ADBE", "HON",
    "CRWD", "CEG", "ADI", "ADP", "DASH", "CMCSA", "VRTX", "MELI", "SBUX",
    "CDNS", "ORLY", "SNPS", "MSTR", "MDLZ", "ABNB", "MRVL", "CTAS", "TRI",
    "MAR", "MNST", "CSX", "ADSK", "PYPL", "FTNT", "AEP", "WDAY", "REGN",
    "ROP", "NXPI", "DDOG", "AXON", "ROST", "IDXX", "EA", "PCAR", "FAST",
    "EXC", "TTWO", "XEL", "ZS", "PAYX", "WBD", "BKR", "CPRT", "CCEP",
    "FANG", "TEAM", "CHTR", "KDP", "MCHP", "GEHC", "VRSK", "CTSH", "CSGP",
    "KHC", "ODFL", "DXCM", "TTD", "ON", "BIIB", "LULU", "CDW", "GFS",
]

all_sse_50_symbols = [
    "600519.SH", "601318.SH", "600036.SH", "601899.SH", "600900.SH",
    "601166.SH", "600276.SH", "600030.SH", "603259.SH", "688981.SH",
    "688256.SH", "601398.SH", "688041.SH", "601211.SH", "601288.SH",
    "601328.SH", "688008.SH", "600887.SH", "600150.SH", "601816.SH",
    "601127.SH", "600031.SH", "688012.SH", "603501.SH", "601088.SH",
    "600309.SH", "601601.SH", "601668.SH", "603993.SH", "601012.SH",
    "601728.SH", "600690.SH", "600809.SH", "600941.SH", "600406.SH",
    "601857.SH", "601766.SH", "601919.SH", "600050.SH", "600760.SH",
    "601225.SH", "600028.SH", "601988.SH", "688111.SH", "601985.SH",
    "601888.SH", "601628.SH", "601600.SH", "601658.SH", "600048.SH",
]


# =============================================================================
# Date Utilities
# =============================================================================

def get_yesterday_date(today_date: str) -> str:
    """Get the previous trading day date.

    Args:
        today_date: Today's date in YYYY-MM-DD format

    Returns:
        Yesterday's date in YYYY-MM-DD format
    """
    today = datetime.strptime(today_date, "%Y-%m-%d")
    yesterday = today - timedelta(days=1)
    # Skip weekends
    while yesterday.weekday() >= 5:  # Saturday=5, Sunday=6
        yesterday -= timedelta(days=1)
    return yesterday.strftime("%Y-%m-%d")


def is_trading_day(date_str: str, market: str = "us") -> bool:
    """Check if a date is a trading day based on merged.jsonl data.

    Args:
        date_str: Date in YYYY-MM-DD format
        market: Market type ('us' or 'cn')

    Returns:
        True if the date is a trading day, False otherwise
    """
    # Determine merged file path based on market
    if market == "cn":
        merged_path = project_root / "data" / "A_stock" / "merged.jsonl"
    else:
        merged_path = project_root / "data" / "merged.jsonl"

    if not merged_path.exists():
        # Fallback: assume weekdays are trading days
        date_obj = datetime.strptime(date_str, "%Y-%m-%d")
        return date_obj.weekday() < 5

    try:
        with open(merged_path, "r", encoding="utf-8") as f:
            for line in f:
                data = json.loads(line)
                time_series = data.get("Time Series (60min)", data.get("Time Series (Daily)", {}))
                for timestamp in time_series.keys():
                    if timestamp.startswith(date_str):
                        return True
    except Exception:
        pass

    return False


# =============================================================================
# Price Data Functions
# =============================================================================

def _load_merged_data(market: str = "us") -> Dict[str, Any]:
    """Load merged price data.

    Args:
        market: Market type ('us' or 'cn')

    Returns:
        Dictionary with symbol as key and price data as value
    """
    if market == "cn":
        merged_path = project_root / "data" / "A_stock" / "merged.jsonl"
    else:
        merged_path = project_root / "data" / "merged.jsonl"

    data_by_symbol = {}
    if merged_path.exists():
        with open(merged_path, "r", encoding="utf-8") as f:
            for line in f:
                entry = json.loads(line)
                symbol = entry.get("Meta Data", {}).get("2. Symbol")
                if symbol:
                    data_by_symbol[symbol] = entry
    return data_by_symbol


def get_open_prices(
    today_date: str,
    stock_symbols: List[str],
    market: str = "us"
) -> Dict[str, float]:
    """Get today's opening prices for given symbols.

    Args:
        today_date: Date in YYYY-MM-DD format
        stock_symbols: List of stock symbols
        market: Market type ('us' or 'cn')

    Returns:
        Dictionary with symbol as key and opening price as value
    """
    merged_data = _load_merged_data(market)
    prices = {}

    for symbol in stock_symbols:
        price = 0.0
        if symbol in merged_data:
            time_series = merged_data[symbol].get(
                "Time Series (60min)",
                merged_data[symbol].get("Time Series (Daily)", {})
            )
            # Find the price for today
            for timestamp, values in time_series.items():
                if timestamp.startswith(today_date):
                    price = float(values.get("1. buy price", values.get("1. open", 0)))
                    break
        prices[symbol] = price

    return prices


def get_yesterday_open_and_close_price(
    today_date: str,
    stock_symbols: List[str],
    market: str = "us"
) -> Tuple[Dict[str, float], Dict[str, float]]:
    """Get yesterday's open and close prices.

    Args:
        today_date: Today's date in YYYY-MM-DD format
        stock_symbols: List of stock symbols
        market: Market type ('us' or 'cn')

    Returns:
        Tuple of (open_prices, close_prices) dictionaries
    """
    yesterday = get_yesterday_date(today_date)
    merged_data = _load_merged_data(market)

    open_prices = {}
    close_prices = {}

    for symbol in stock_symbols:
        open_price = 0.0
        close_price = 0.0

        if symbol in merged_data:
            time_series = merged_data[symbol].get(
                "Time Series (60min)",
                merged_data[symbol].get("Time Series (Daily)", {})
            )
            # Find prices for yesterday
            for timestamp, values in time_series.items():
                if timestamp.startswith(yesterday):
                    open_price = float(values.get("1. buy price", values.get("1. open", 0)))
                    close_price = float(values.get("4. sell price", values.get("4. close", 0)))
                    break

        open_prices[symbol] = open_price
        close_prices[symbol] = close_price

    return open_prices, close_prices


def format_price_dict_with_names(prices: Dict[str, float]) -> str:
    """Format price dictionary as a readable string.

    Args:
        prices: Dictionary with symbol as key and price as value

    Returns:
        Formatted string representation
    """
    lines = []
    for symbol, price in prices.items():
        lines.append(f"{symbol}: ${price:.2f}")
    return "\n".join(lines)


def get_yesterday_profit(
    today_date: str,
    buy_prices: Dict[str, float],
    sell_prices: Dict[str, float],
    positions: Dict[str, Any]
) -> float:
    """Calculate yesterday's profit.

    Args:
        today_date: Today's date
        buy_prices: Yesterday's buy prices
        sell_prices: Yesterday's sell prices
        positions: Current positions

    Returns:
        Total profit
    """
    profit = 0.0
    for symbol, qty in positions.items():
        if symbol == "CASH" or not isinstance(qty, (int, float)):
            continue
        if qty > 0 and symbol in buy_prices and symbol in sell_prices:
            profit += qty * (sell_prices[symbol] - buy_prices[symbol])
    return profit


# =============================================================================
# Position Management Functions
# =============================================================================

def _get_position_file_path(signature: str) -> Path:
    """Get the position file path for a given signature.

    Args:
        signature: Agent signature

    Returns:
        Path to position.jsonl file
    """
    log_path = get_config_value("LOG_PATH", "./data/agent_data")
    if log_path.startswith("./data/"):
        log_rel = log_path[7:]
    else:
        log_rel = log_path
    return project_root / "data" / log_rel / signature / "position" / "position.jsonl"


def _get_next_id(signature: str) -> int:
    """Get the next ID for position log entry.

    Args:
        signature: Agent signature

    Returns:
        Next ID number
    """
    position_file = _get_position_file_path(signature)
    max_id = -1

    if position_file.exists():
        with open(position_file, "r", encoding="utf-8") as f:
            for line in f:
                try:
                    entry = json.loads(line)
                    entry_id = entry.get("id", 0)
                    if entry_id > max_id:
                        max_id = entry_id
                except json.JSONDecodeError:
                    continue

    return max_id + 1


def get_today_init_position(today_date: str, signature: str) -> Dict[str, Any]:
    """Get today's initial position from position.jsonl.

    Args:
        today_date: Today's date
        signature: Agent signature

    Returns:
        Position dictionary
    """
    position_file = _get_position_file_path(signature)

    if not position_file.exists():
        return {"CASH": 10000.0}

    latest_position = None
    with open(position_file, "r", encoding="utf-8") as f:
        for line in f:
            try:
                entry = json.loads(line)
                if latest_position is None or entry.get("id", 0) > latest_position.get("id", 0):
                    latest_position = entry
            except json.JSONDecodeError:
                continue

    if latest_position:
        return latest_position.get("positions", {"CASH": 10000.0})
    return {"CASH": 10000.0}


def add_no_trade_record(today_date: str, signature: str) -> None:
    """Add a no-trade record to position.jsonl (maintains previous position).

    Args:
        today_date: Today's date
        signature: Agent signature
    """
    position_file = _get_position_file_path(signature)
    position_file.parent.mkdir(parents=True, exist_ok=True)

    # Get current position
    positions = get_today_init_position(today_date, signature)
    next_id = _get_next_id(signature)

    entry = {
        "date": today_date,
        "id": next_id,
        "positions": positions,
    }

    with open(position_file, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")


# =============================================================================
# KIS Position Sync Functions (Task 7.2)
# =============================================================================

def sync_kis_position_to_log(signature: str, date: str) -> None:
    """Sync KIS API balance to position.jsonl.

    Retrieves the current balance from KIS API and records it to position.jsonl
    with source='kis_api' to distinguish from local simulated positions.

    Args:
        signature: Agent signature
        date: Date in YYYY-MM-DD format
    """
    from integrations.kis_settings import is_kis_broker

    if not is_kis_broker():
        return

    from agent_tools.kis_context import kis_balance_adapter

    # Get KIS balance
    try:
        balance = kis_balance_adapter()
    except Exception as e:
        print(f"⚠️ Failed to get KIS balance: {e}")
        return

    # Extract pure position data (exclude internal metadata fields)
    positions = {}
    for key, value in balance.items():
        if not key.startswith("_"):
            positions[key] = value

    # Get position file path and next ID
    position_file = _get_position_file_path(signature)
    position_file.parent.mkdir(parents=True, exist_ok=True)
    next_id = _get_next_id(signature)

    entry = {
        "date": date,
        "id": next_id,
        "positions": positions,
        "source": "kis_api",
    }

    with open(position_file, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")

    print(f"✅ KIS position synced to {position_file}")


# =============================================================================
# Log Consistency Validation (Task 7.4)
# =============================================================================

def validate_log_consistency(
    signature: str,
    date: str
) -> Dict[str, Any]:
    """Validate consistency between kis_orders.jsonl and position.jsonl.

    Checks that orders recorded in kis_orders.jsonl are reflected correctly
    in position changes in position.jsonl for the given date.

    Args:
        signature: Agent signature
        date: Date to validate in YYYY-MM-DD format

    Returns:
        Validation result dictionary with:
            - is_valid: bool
            - inconsistencies: list of inconsistency details
            - orders_count: number of orders found
            - position_changes: position changes detected
    """
    log_path = get_config_value("LOG_PATH", "./data/agent_data")
    if log_path.startswith("./data/"):
        log_rel = log_path[7:]
    else:
        log_rel = log_path

    base_dir = project_root / "data" / log_rel / signature / "position"
    orders_file = base_dir / "kis_orders.jsonl"
    position_file = base_dir / "position.jsonl"

    result = {
        "is_valid": True,
        "inconsistencies": [],
        "orders_count": 0,
        "position_changes": {},
        "date": date,
    }

    # Load orders for the date
    orders = []
    if orders_file.exists():
        with open(orders_file, "r", encoding="utf-8") as f:
            for line in f:
                try:
                    order = json.loads(line)
                    if order.get("date") == date:
                        orders.append(order)
                except json.JSONDecodeError:
                    continue

    result["orders_count"] = len(orders)

    # Calculate expected position changes from orders
    expected_changes = {}
    for order in orders:
        symbol = order.get("symbol")
        side = order.get("side")
        qty = order.get("qty", 0)

        if symbol and side:
            if symbol not in expected_changes:
                expected_changes[symbol] = 0
            if side == "buy":
                expected_changes[symbol] += qty
            elif side == "sell":
                expected_changes[symbol] -= qty

    # Load positions for the date
    positions_on_date = []
    if position_file.exists():
        with open(position_file, "r", encoding="utf-8") as f:
            for line in f:
                try:
                    pos = json.loads(line)
                    if pos.get("date") == date:
                        positions_on_date.append(pos)
                except json.JSONDecodeError:
                    continue

    # Calculate actual position changes
    if len(positions_on_date) >= 2:
        # Sort by ID
        positions_on_date.sort(key=lambda x: x.get("id", 0))
        first_pos = positions_on_date[0].get("positions", {})
        last_pos = positions_on_date[-1].get("positions", {})

        all_symbols = set(first_pos.keys()) | set(last_pos.keys())
        for symbol in all_symbols:
            if symbol == "CASH":
                continue
            first_qty = first_pos.get(symbol, 0)
            last_qty = last_pos.get(symbol, 0)
            change = last_qty - first_qty
            if change != 0:
                result["position_changes"][symbol] = change

    # Compare expected vs actual changes
    for symbol, expected_change in expected_changes.items():
        actual_change = result["position_changes"].get(symbol, 0)
        if expected_change != actual_change:
            result["is_valid"] = False
            result["inconsistencies"].append({
                "symbol": symbol,
                "expected_change": expected_change,
                "actual_change": actual_change,
                "difference": actual_change - expected_change,
            })

    if not result["is_valid"]:
        print(f"⚠️ Log inconsistency detected for {signature} on {date}:")
        for inc in result["inconsistencies"]:
            print(f"   {inc['symbol']}: expected {inc['expected_change']}, actual {inc['actual_change']}")

    return result


def get_orders_for_date(signature: str, date: str) -> List[Dict[str, Any]]:
    """Get all KIS orders for a specific date.

    Args:
        signature: Agent signature
        date: Date in YYYY-MM-DD format

    Returns:
        List of order dictionaries
    """
    log_path = get_config_value("LOG_PATH", "./data/agent_data")
    if log_path.startswith("./data/"):
        log_rel = log_path[7:]
    else:
        log_rel = log_path

    orders_file = project_root / "data" / log_rel / signature / "position" / "kis_orders.jsonl"
    orders = []

    if orders_file.exists():
        with open(orders_file, "r", encoding="utf-8") as f:
            for line in f:
                try:
                    order = json.loads(line)
                    if order.get("date") == date:
                        orders.append(order)
                except json.JSONDecodeError:
                    continue

    return orders
