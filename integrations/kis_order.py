"""KIS 해외주식 주문 래퍼.

KIS Open API [해외주식] 주문/계좌
- 해외주식 주문[v1_해외주식-001/002]: 매수/매도 주문
- 해외주식 정정취소주문[v1_해외주식-003]: 주문 정정/취소
- 해외주식 미체결내역[v1_해외주식-005]: 미체결 주문 조회
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Dict, List, Literal, Optional

from integrations.kis_client import KISRestClient
from integrations.kis_settings import KISSettings
from models.broker import OrderResult

logger = logging.getLogger(__name__)

Side = Literal["buy", "sell"]


@dataclass(frozen=True)
class PendingOrder:
    """미체결 주문 정보."""

    order_no: str
    symbol: str
    side: str
    qty: int
    filled_qty: int
    pending_qty: int
    price: float
    order_time: str
    exchange: str
    raw: Dict[str, Any]


@dataclass(frozen=True)
class CancelResult:
    """주문 취소 결과."""

    order_no: str
    original_order_no: str
    message: str


class KISOrderService:
    """모의 해외주식 지정가 주문을 수행한다."""

    _TR_ID_MAP: Dict[Side, str] = {"buy": "VTTT1002U", "sell": "VTTT1001U"}
    _TR_ID_CANCEL: str = "VTTT1004U"  # 모의투자 정정취소
    _TR_ID_PENDING: str = "VTTS3018R"  # 모의투자 미체결내역 (실전: TTTS3018R)

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

    def get_pending_orders(self, exchange: Optional[str] = None) -> List[PendingOrder]:
        """미체결 주문 내역을 조회합니다.

        Args:
            exchange: 거래소 코드 (기본값: self.exchange, "NASD"면 미국 전체)

        Returns:
            List[PendingOrder]: 미체결 주문 목록
        """
        excg = exchange or self.exchange
        params = {
            "CANO": self.account,
            "ACNT_PRDT_CD": self.product,
            "OVRS_EXCG_CD": excg,
            "SORT_SQN": "DS",
            "CTX_AREA_FK200": "",
            "CTX_AREA_NK200": "",
        }

        try:
            payload = self.client.request(
                "GET",
                "/uapi/overseas-stock/v1/trading/inquire-nccs",
                tr_id=self._TR_ID_PENDING,
                params=params,
                paginate=True,
            )
        except Exception as exc:
            logger.error("KIS 미체결 조회 실패: %s", exc)
            raise ValueError(f"KIS 미체결 조회 실패: {exc}") from exc

        if isinstance(payload, dict):
            pages = [payload]
        else:
            pages = payload

        pending_orders: List[PendingOrder] = []
        for page in pages:
            items = page.get("output", [])
            for item in items:
                try:
                    symbol = item.get("pdno", "")
                    if not symbol:
                        continue

                    order_no = item.get("odno", "")
                    side_code = item.get("sll_buy_dvsn_cd", "")
                    side = "sell" if side_code == "01" else "buy"

                    qty = int(float(item.get("ft_ord_qty", "0")))
                    filled_qty = int(float(item.get("ft_ccld_qty", "0")))
                    pending_qty = int(float(item.get("nccs_qty", "0")))
                    price = float(item.get("ft_ord_unpr3", "0"))
                    order_time = item.get("ord_tmd", "")
                    exchange_code = item.get("ovrs_excg_cd", "")

                    pending_orders.append(PendingOrder(
                        order_no=order_no,
                        symbol=symbol,
                        side=side,
                        qty=qty,
                        filled_qty=filled_qty,
                        pending_qty=pending_qty,
                        price=price,
                        order_time=order_time,
                        exchange=exchange_code,
                        raw=item,
                    ))
                except (KeyError, ValueError) as e:
                    logger.error("미체결 주문 파싱 실패: %s -> %s", item, e)

        return pending_orders

    def cancel_order(
        self,
        original_order_no: str,
        symbol: str,
        qty: int,
        exchange: Optional[str] = None,
    ) -> CancelResult:
        """주문을 취소합니다.

        Args:
            original_order_no: 취소할 원주문번호
            symbol: 종목 심볼
            qty: 취소 수량
            exchange: 거래소 코드 (기본값: self.exchange)

        Returns:
            CancelResult: 취소 결과
        """
        if not original_order_no:
            raise ValueError("original_order_no는 비어 있을 수 없습니다.")
        if not symbol:
            raise ValueError("symbol은 비어 있을 수 없습니다.")
        if qty <= 0:
            raise ValueError("qty는 0보다 커야 합니다.")

        excg = exchange or self.exchange
        sym = symbol.strip().upper()

        body = {
            "CANO": self.account,
            "ACNT_PRDT_CD": self.product,
            "OVRS_EXCG_CD": excg,
            "PDNO": sym,
            "ORGN_ODNO": original_order_no,
            "RVSE_CNCL_DVSN_CD": "02",  # 02: 취소
            "ORD_QTY": str(qty),
            "OVRS_ORD_UNPR": "0",  # 취소 시 0 입력
            "MGCO_APTM_ODNO": "",
            "ORD_SVR_DVSN_CD": "0",
        }

        try:
            payload = self.client.request(
                "POST",
                "/uapi/overseas-stock/v1/trading/order-rvsecncl",
                tr_id=self._TR_ID_CANCEL,
                data=body,
                paginate=False,
            )
        except Exception as exc:
            raise ValueError(f"KIS 주문 취소 실패: {sym}: {exc}") from exc

        output = payload.get("output") if isinstance(payload, dict) else None
        if not output:
            raise ValueError(f"KIS 주문 취소 응답에 output이 없습니다: {sym}")

        new_order_no = output.get("ODNO", "")
        order_time = output.get("ORD_TMD", "")

        return CancelResult(
            order_no=new_order_no,
            original_order_no=original_order_no,
            message=f"취소 완료: {order_time}",
        )


__all__ = ["KISOrderService", "PendingOrder", "CancelResult"]
