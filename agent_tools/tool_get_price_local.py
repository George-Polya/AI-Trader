import os
import sys
from typing import Any, Dict
from pathlib import Path

from dotenv import load_dotenv
from fastmcp import FastMCP

# Add parent directory to Python path to import tools module
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

load_dotenv()

mcp = FastMCP("LocalPrices")

# Ensure project root is on sys.path for absolute imports like `tools.*`
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from integrations.kis_settings import is_kis_broker
from agent_tools.kis_context import kis_quote_adapter


@mcp.tool()
def get_price_local(symbol: str, date: str) -> Dict[str, Any]:
    """Read OHLCV data for specified stock and date. Get historical information for specified stock.
    
    Automatically detects date format and calls appropriate function:
    - Daily data: YYYY-MM-DD format (e.g., '2025-10-30')
    - Hourly data: YYYY-MM-DD HH:MM:SS format (e.g., '2025-10-30 14:30:00')

    Args:
        symbol: Stock symbol, e.g. 'IBM' or '600243.SHH'.
        date: Date in 'YYYY-MM-DD' or 'YYYY-MM-DD HH:MM:SS' format. Based on your current time format.

    Returns:
        Dictionary containing symbol, date and ohlcv data.
    """
    if not is_kis_broker():
        return {"error": "This agent only supports KIS broker mode. Please set BROKER=kis."}

    try:
        quote = kis_quote_adapter(symbol)
        return {
            "symbol": symbol,
            "date": date,
            "broker": "kis",
            "source": "kis",
            "ohlcv": {
                "open": None,
                "high": None,
                "low": None,
                "close": quote.last,
                "volume": quote.volume,
            },
        }
    except Exception as exc:
        return {
            "error": f"KIS 시세 조회 실패: {exc}",
            "symbol": symbol,
            "date": date,
            "broker": "kis",
        }


if __name__ == "__main__":
    
    port = int(os.getenv("GETPRICE_HTTP_PORT", "8003"))
    mcp.run(transport="streamable-http", port=port)