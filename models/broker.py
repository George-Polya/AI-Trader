"""공통 브로커 데이터 모델."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


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
