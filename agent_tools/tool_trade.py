import os
import sys
from typing import Any, Dict, List, Optional
from pathlib import Path
import json

from fastmcp import FastMCP

# Add project root directory to Python path
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, project_root)

from tools.general_tools import get_config_value
from integrations.kis_settings import is_kis_broker
from agent_tools.kis_context import kis_order_adapter, kis_balance_adapter

mcp = FastMCP("TradeTools")


def _log_kis_order(
    result: Any,
    side: str,
    symbol: str,
    qty: int,
    price: float
) -> None:
    """Log KIS order result to kis_orders.jsonl with extended format.

    Args:
        result: KIS API order result object
        side: Order side ('buy' or 'sell')
        symbol: Stock symbol (e.g., 'AAPL')
        qty: Order quantity
        price: Limit price for the order
    """
    from datetime import datetime

    log_path = get_config_value("LOG_PATH", "./data/agent_data")
    signature = get_config_value("SIGNATURE") or "unknown"
    today_date = get_config_value("TODAY_DATE")

    if log_path.startswith("./data/"):
        log_rel = log_path[7:]
    else:
        log_rel = log_path

    base_dir = Path(project_root) / "data" / log_rel / signature / "position"
    base_dir.mkdir(parents=True, exist_ok=True)

    log_file = base_dir / "kis_orders.jsonl"

    entry = {
        "timestamp": datetime.now().isoformat(),
        "date": today_date,  # YYYY-MM-DD format for position.jsonl consistency
        "order_no": result.order_no,
        "symbol": symbol,
        "side": side,
        "qty": qty,
        "limit_price": price,
        "message": result.message,
        "status": "submitted",  # submitted, filled, cancelled
        "broker": "kis",
        "source": "kis_api",
        "raw": getattr(result, "raw", {}),
    }

    with open(log_file, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")


@mcp.tool()
def get_position() -> Dict[str, Any]:
    """
    Get current position information.
    
    Returns:
        Dict[str, Any]: Dictionary containing symbol quantities and CASH balance.
    """
    if not is_kis_broker():
        return {"error": "This agent only supports KIS broker mode. Please set BROKER=kis."}

    try:
        res = kis_balance_adapter()
        res["broker"] = "kis"
        return res
    except Exception as e:
        return {"error": str(e), "broker": "kis"}


@mcp.tool()
def buy(symbol: str, amount: int, limit_price: Optional[float] = None) -> Dict[str, Any]:
    """
    Buy stock function via KIS API.

    Args:
        symbol: Stock symbol, such as "AAPL", "MSFT", etc.
        amount: Buy quantity, must be a positive integer.
        limit_price: Limit price for the order. Required for KIS broker.

    Returns:
        Dict[str, Any]: Order result.
    """
    if not is_kis_broker():
        return {"error": "This agent only supports KIS broker mode. Please set BROKER=kis."}

    if limit_price is None:
        raise ValueError("limit_price required for KIS broker")
    try:
        res = kis_order_adapter(symbol, amount, limit_price, "buy")
        _log_kis_order(res, side="buy", symbol=symbol, qty=amount, price=limit_price)
        return {
            "order_no": res.order_no,
            "status": res.message,
            "broker": "kis",
            "side": "buy",
            "symbol": symbol,
            "qty": amount,
            "price": limit_price
        }
    except Exception as e:
        return {"error": str(e), "broker": "kis"}


@mcp.tool()
def sell(symbol: str, amount: int, limit_price: Optional[float] = None) -> Dict[str, Any]:
    """
    Sell stock function via KIS API.

    Args:
        symbol: Stock symbol, such as "AAPL", "MSFT", etc.
        amount: Sell quantity, must be a positive integer.
        limit_price: Limit price for the order. Required for KIS broker.

    Returns:
        Dict[str, Any]: Order result.
    """
    if not is_kis_broker():
        return {"error": "This agent only supports KIS broker mode. Please set BROKER=kis."}

    if limit_price is None:
        raise ValueError("limit_price required for KIS broker")
    try:
        res = kis_order_adapter(symbol, amount, limit_price, "sell")
        _log_kis_order(res, side="sell", symbol=symbol, qty=amount, price=limit_price)
        return {
            "order_no": res.order_no,
            "status": res.message,
            "broker": "kis",
            "side": "sell",
            "symbol": symbol,
            "qty": amount,
            "price": limit_price
        }
    except Exception as e:
        return {"error": str(e), "broker": "kis"}


if __name__ == "__main__":
    port = int(os.getenv("TRADE_HTTP_PORT", "8002"))
    mcp.run(transport="streamable-http", port=port)