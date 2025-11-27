"""공통 브로커 데이터 모델."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional, Dict, Any


@dataclass(frozen=True)
class Quote:
    """해외주식 시세를 표현하는 모델."""

    symbol: str
    last: float
    prev_close: float
    change: float
    change_rate: float
    volume: Optional[int] = None


@dataclass(frozen=True)
class OrderResult:
    """주문 결과를 표현하는 모델."""

    order_no: str
    message: str
    side: str
    symbol: str
    qty: int
    limit_price: float


@dataclass(frozen=True)
class BalanceLine:
    """계좌 잔고 항목을 표현하는 모델."""

    symbol: str
    qty: int
    value: float
    currency: str
    raw: Dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class Execution:
    """체결 내역을 표현하는 모델."""

    symbol: str
    qty: int
    price: float
    status: str
    side: str
    order_no: str
    filled_at: str
    raw: Dict[str, Any] = field(default_factory=dict)