"""해외주식 시세 조회 서비스."""

from __future__ import annotations

from typing import Any, Dict, Optional

from integrations.kis_client import KISRestClient
from models.broker import Quote


class KISQuoteService:
    """KIS 해외주식 시세 조회 래퍼."""

    def __init__(self, client: KISRestClient, *, market: str = "NASD") -> None:
        self.client = client
        self.market = market

    def _validate_symbol(self, symbol: str) -> str:
        normalized = (symbol or "").strip().upper()
        if not normalized:
            raise ValueError("symbol은 비어 있을 수 없습니다.")
        return normalized

    def _build_params(self, symbol: str) -> Dict[str, Any]:
        return {
            "FID_COND_MRKT_DIV_CODE": "J",
            "FID_INPUT_ISCD": symbol,
            "FID_INPUT_ISCD2": "",
            "FID_INPUT_DATE_1": "",
            "FID_INPUT_DATE_2": "",
            "FID_INPUT_DATE_3": "",
            "EXCD": self.market,
            "SYMB": symbol,
        }

    def get_quote(self, symbol: str) -> Quote:
        symbol_norm = self._validate_symbol(symbol)
        params = self._build_params(symbol_norm)
        try:
            payload = self.client.request(
                "GET",
                "/uapi/overseas-price/v1/quotations/price",
                tr_id="HHDFS00000300",
                params=params,
                paginate=False,
            )
        except Exception as exc:
            raise ValueError(f"KIS 시세 조회 실패: {symbol_norm}: {exc}") from exc

        output: Optional[Dict[str, Any]] = payload.get("output") if isinstance(payload, dict) else None
        if not output:
            raise ValueError(f"KIS 시세 응답에 output이 없습니다: {symbol_norm}")

        try:
            last = float(output["ovrs_nmix_prpr"])
            prev_close = float(output["ovrs_nmix_basp_prc"])
            change = float(output["ovrs_nmix_prdy_vrss_prc"])
            change_rate = float(output["ovrs_nmix_prdy_ctrt"])
            vol_raw = output.get("ovrs_nmix_vol")
            volume = int(vol_raw) if vol_raw not in (None, "") else None
        except Exception as exc:  # 작은 범위 변환 오류만 잡음
            raise ValueError(f"KIS 시세 응답 파싱 실패: {symbol_norm}: {exc}") from exc

        return Quote(
            symbol=symbol_norm,
            last=last,
            prev_close=prev_close,
            change=change,
            change_rate=change_rate,
            volume=volume,
        )


__all__ = ["KISQuoteService"]
