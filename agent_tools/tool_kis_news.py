"""KIS 해외주식 뉴스 MCP 도구.

Alpha Vantage 뉴스 도구를 대체하여 KIS API를 사용합니다.
기존 인터페이스(get_market_news)를 유지하여 BaseAgent와 호환됩니다.
"""

import os
import sys
from datetime import datetime
from typing import Optional

from fastmcp import FastMCP

# Add project root directory to Python path
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, project_root)

from tools.general_tools import get_config_value
from integrations.kis_settings import is_kis_broker
from agent_tools.kis_context import kis_news_adapter

mcp = FastMCP("Search")


def _format_date_for_kis(date_str: Optional[str]) -> Optional[str]:
    """TODAY_DATE 형식을 KIS API 형식(YYYYMMDD)으로 변환합니다.

    Args:
        date_str: "YYYY-MM-DD" 또는 "YYYY-MM-DD HH:MM:SS" 형식

    Returns:
        "YYYYMMDD" 형식 또는 None
    """
    if not date_str:
        return None
    try:
        # "YYYY-MM-DD HH:MM:SS" 형식 처리
        if " " in date_str:
            date_part = date_str.split(" ")[0]
        else:
            date_part = date_str

        dt = datetime.strptime(date_part, "%Y-%m-%d")
        return dt.strftime("%Y%m%d")
    except ValueError:
        return None


def _format_output(articles: list) -> str:
    """뉴스 기사 목록을 문자열로 포맷합니다.

    Alpha Vantage 출력 형식과 유사하게 구성합니다.
    """
    if not articles:
        return "No news articles found."

    formatted_results = []
    for article in articles:
        # 날짜 형식 변환 (YYYYMMDD -> YYYY-MM-DD)
        date_formatted = article.date
        if len(article.date) == 8:
            try:
                dt = datetime.strptime(article.date, "%Y%m%d")
                date_formatted = dt.strftime("%Y-%m-%d")
            except ValueError:
                pass

        # 시간 형식 변환 (HHMMSS -> HH:MM:SS)
        time_formatted = article.time
        if len(article.time) == 6:
            try:
                time_formatted = f"{article.time[:2]}:{article.time[2:4]}:{article.time[4:]}"
            except (ValueError, IndexError):
                pass

        result = f"""Title: {article.title}
Source: {article.source}
Date: {date_formatted} {time_formatted}
Symbol: {article.symbol or 'N/A'} ({article.symbol_name or 'N/A'})
Category: {article.category or 'N/A'}
--------------------------------"""
        formatted_results.append(result)

    return "\n".join(formatted_results)


@mcp.tool()
def get_market_news(
    query: str,
    tickers: Optional[str] = None,
    topics: Optional[str] = None
) -> str:
    """
    Retrieve market news articles using KIS News API.
    Only returns articles published before TODAY_DATE (as configured in runtime config).

    This tool replaces the Alpha Vantage news tool and uses KIS (Korea Investment & Securities)
    API for fetching overseas stock news.

    Args:
        query: Search query description (used for logging purposes, not for filtering)
        tickers: Optional. Stock symbols to filter by.
                Examples: "AAPL" or "MSFT,GOOG" (only first ticker is used)
        topics: Optional. News topics (not supported by KIS API, kept for compatibility)

    Returns:
        A formatted string containing news articles with:
        - Title: Article title
        - Source: News source
        - Date/Time: Publication date and time
        - Symbol: Related stock symbol and name
        - Category: News category
    """
    if not is_kis_broker():
        return "Error: This tool requires KIS broker mode. Please set BROKER=kis in your environment."

    try:
        # Get TODAY_DATE for filtering
        today_date = get_config_value("TODAY_DATE")
        kis_date = _format_date_for_kis(today_date)

        # Parse tickers (support comma-separated list, use first one)
        symbol = None
        if tickers:
            symbol = tickers.split(",")[0].strip().upper()

        # Call KIS news adapter
        articles = kis_news_adapter(
            symbol=symbol,
            date=kis_date,
            max_results=20
        )

        if not articles:
            msg = f"No news articles found"
            if tickers:
                msg += f" for ticker(s): {tickers}"
            if today_date:
                msg += f" as of {today_date}"
            return msg

        return _format_output(articles)

    except Exception as e:
        return f"KIS news tool execution failed: {str(e)}"


if __name__ == "__main__":
    port = int(os.getenv("SEARCH_HTTP_PORT", "8001"))
    print(f"Starting KIS News MCP service on port {port}...")
    mcp.run(transport="streamable-http", port=port)
