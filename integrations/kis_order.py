"""KIS 해외주식 주문 래퍼."""

from __future__ import annotations

from typing import Any, Dict, Literal, Optional

from integrations.kis_client import KISRestClient
from integrations.kis_settings import KISSettings
from models.broker import OrderResult

Side = Literal["buy", "sell"]


class KISOrderService:
    """모의 해외주식 지정가 주문을 수행한다."""

    _TR_ID_MAP: Dict[Side, str] = {"buy": "VTTT1002U", "sell": "VTTT1001U"}

    def __init__(
        self,
        client: KISRestClient,
        settings: KISSettings,
        *,
        exchange: str = "NASD",
        account: Optional[str] = None,
        product: Optional[str] = None,
    ) -> None:
        self.client = client
        self.settings = settings
        self.exchange = exchange
        self.account = account or settings.my_paper_stock
        self.product = product or settings.my_prod

    def _validate(self, symbol: str, qty: int, limit_price: float, side: Side) -> tuple[str, int, float, Side]:
        sym = (symbol or "").strip().upper()
        if not sym:
            raise ValueError("symbol은 비어 있을 수 없습니다.")
        try:
            qty_int = int(qty)
        except Exception as exc:
            raise ValueError("qty는 정수여야 합니다.") from exc
        if qty_int <= 0:
            raise ValueError("qty는 0보다 커야 합니다.")
        try:
            price_f = float(limit_price)
        except Exception as exc:
            raise ValueError("limit_price는 숫자여야 합니다.") from exc
        if price_f <= 0:
            raise ValueError("limit_price는 0보다 커야 합니다.")
        if side not in self._TR_ID_MAP:
            raise ValueError("side는 buy 또는 sell이어야 합니다.")
        return sym, qty_int, price_f, side

    def _build_body(self, symbol: str, qty: int, limit_price: float) -> Dict[str, Any]:
        return {
            "CANO": self.account,
            "ACNT_PRDT_CD": self.product,
            "OVRS_EXCG_CD": self.exchange,
            "OVRS_PDNO": symbol,
            "OVRS_ORD_UNPR": f"{limit_price:.2f}",
            "OVRS_ORD_QTY": str(qty),
            "ORD_DVSN": "00",  # 지정가
        }

    def submit_order(self, symbol: str, qty: int, limit_price: float, side: Side) -> OrderResult:
        sym, qty_int, price_f, side_norm = self._validate(symbol, qty, limit_price, side)
        body = self._build_body(sym, qty_int, price_f)
        tr_id = self._TR_ID_MAP[side_norm]
        try:
            payload = self.client.request(
                "POST",
                "/uapi/overseas-stock/v1/trading/order",
                tr_id=tr_id,
                data=body,
                paginate=False,
            )
        except Exception as exc:
            raise ValueError(f"KIS 주문 실패: {sym}: {exc}") from exc

        output = payload.get("output") if isinstance(payload, dict) else None
        if not output:
            raise ValueError(f"KIS 주문 응답에 output이 없습니다: {sym}")

        order_no = output.get("ODNO") or output.get("ODNO_ORG")
        if not order_no:
            raise ValueError(f"KIS 주문 응답에 주문번호가 없습니다: {sym}")

        message = output.get("ORD_TMD") or output.get("msg1") or ""

        return OrderResult(
            order_no=str(order_no),
            message=str(message),
            side=side_norm,
            symbol=sym,
            qty=qty_int,
            limit_price=price_f,
        )


__all__ = ["KISOrderService"]
