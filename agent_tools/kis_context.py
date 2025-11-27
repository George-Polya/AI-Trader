import os
from typing import Any, Dict, List, Optional, Union
import json

from tools.general_tools import get_config_value
from integrations.kis_order import KISOrderService
from integrations.kis_account import KISAccountService
from integrations.kis_auth_manager import KISAuthenticator
from integrations.kis_client import KISRestClient
from integrations.kis_quote import KISQuoteService
from integrations.kis_settings import KISSettings, is_kis_broker, load_kis_settings
from models.broker import Quote, OrderResult, BalanceLine, Execution

_settings_cache: Optional[KISSettings] = None
_quote_service_cache: Optional[KISQuoteService] = None
_order_service_cache: Optional[KISOrderService] = None
_account_service_cache: Optional[KISAccountService] = None

def ensure_kis_settings(path: str | None = None) -> KISSettings:
    global _settings_cache
    if not is_kis_broker():
        raise RuntimeError("BROKER가 kis가 아니어서 KIS 설정을 로드하지 않습니다.")
    if _settings_cache is not None and path is None:
        return _settings_cache
    try:
        settings = load_kis_settings(path)
    except Exception as exc:
        raise RuntimeError(f"KIS 설정 로드에 실패했습니다: {exc}") from exc
    _settings_cache = settings
    return settings

def _get_kis_client() -> KISRestClient:
    settings = ensure_kis_settings()
    authenticator = KISAuthenticator(settings, svr="vps", product="01")
    return KISRestClient(authenticator)

def ensure_kis_quote_service() -> KISQuoteService:
    global _quote_service_cache
    if _quote_service_cache is not None:
        return _quote_service_cache
    client = _get_kis_client()
    service = KISQuoteService(client)
    _quote_service_cache = service
    return service

def ensure_kis_order_service() -> KISOrderService:
    global _order_service_cache
    if _order_service_cache is not None:
        return _order_service_cache
    settings = ensure_kis_settings()
    client = _get_kis_client()
    service = KISOrderService(client, settings)
    _order_service_cache = service
    return service

def ensure_kis_account_service() -> KISAccountService:
    global _account_service_cache
    if _account_service_cache is not None:
        return _account_service_cache
    settings = ensure_kis_settings()
    client = _get_kis_client()
    service = KISAccountService(client, settings)
    _account_service_cache = service
    return service

def kis_quote_adapter(symbol: str) -> Quote:
    service = ensure_kis_quote_service()
    return service.get_quote(symbol)

def kis_order_adapter(symbol: str, qty: int, price: float, side: str) -> OrderResult:
    service = ensure_kis_order_service()
    return service.submit_order(symbol, qty, price, side)

def kis_balance_adapter() -> Dict[str, Any]:
    """KIS 잔고와 체결 내역을 조회하여 에이전트가 이해할 수 있는 포맷으로 반환."""
    service = ensure_kis_account_service()
    
    # 1. 잔고 조회
    balances = service.get_balance()
    
    # 2. 최근 체결 내역 조회 (오늘 기준)
    fills = service.get_fills()

    # 3. 예수금(매수 가능 금액) 조회
    try:
        cash_balance = service.get_cash_balance()
    except Exception:
        cash_balance = 0.0
    
    # 4. 포맷 변환
    position_dict = {}
    total_value = 0.0
    
    for b in balances:
        position_dict[b.symbol] = b.qty
        total_value += b.value
        
    position_dict["CASH"] = cash_balance
    position_dict["_TOTAL_VALUE"] = total_value + cash_balance

    def _normalize_side(raw_side: str) -> str:
        """한글 매수/매도를 영문 buy/sell로 변환."""
        s = raw_side.strip()
        if "매수" in s:
            return "buy"
        if "매도" in s:
            return "sell"
        return s

    position_dict["_FILLS"] = [
        {
            "symbol": f.symbol,
            "qty": f.qty,
            "price": f.price,
            "side": _normalize_side(f.side),
            "status": f.status,
            "time": f.filled_at
        }
        for f in fills
    ]
    
    return position_dict