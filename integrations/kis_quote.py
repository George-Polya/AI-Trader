"""해외주식 시세 조회 서비스.

KIS Open API [해외주식] 기본시세 > 해외주식 현재체결가 [v1_해외주식-009]
TR ID: HHDFS00000300 (실전/모의투자 공통)

응답 필드 매핑:
  - rsym: 실시간조회종목코드
  - zdiv: 소수점자리수
  - base: 전일종가
  - pvol: 전일거래량
  - last: 현재가
  - sign: 대비기호
  - diff: 대비
  - rate: 등락율
  - tvol: 거래량
  - tamt: 거래대금
  - ordy: 매수가능여부
"""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional

from integrations.kis_client import KISRestClient
from models.broker import Quote

logger = logging.getLogger(__name__)

# 거래소 코드 매핑 (일반적인 이름 → KIS API 코드)
# 참조: KIS Open API 해외주식 현재체결가[v1_해외주식-009] 문서
EXCHANGE_CODES = {
    # 미국 정규시장
    "NASD": "NAS",     # 나스닥
    "NASDAQ": "NAS",
    "NAS": "NAS",
    "NYSE": "NYS",     # 뉴욕
    "NYS": "NYS",
    "AMEX": "AMS",     # 아멕스
    "AMS": "AMS",
    # 미국 주간거래
    "BAY": "BAY",      # 뉴욕(주간)
    "BAQ": "BAQ",      # 나스닥(주간)
    "BAA": "BAA",      # 아멕스(주간)
    # 아시아
    "HKS": "HKS",      # 홍콩
    "HKEX": "HKS",
    "TSE": "TSE",      # 도쿄
    "TYO": "TSE",
    "SHS": "SHS",      # 상해
    "SHA": "SHS",
    "SZS": "SZS",      # 심천
    "SHE": "SZS",
    "SHI": "SHI",      # 상해지수
    "SZI": "SZI",      # 심천지수
    "HSX": "HSX",      # 호치민
    "HNX": "HNX",      # 하노이
}

# 유효한 거래소 코드 집합
VALID_EXCHANGE_CODES = frozenset(EXCHANGE_CODES.values())


class KISQuoteService:
    """KIS 해외주식 시세 조회 래퍼.

    해외 주식 현재가를 조회합니다.

    Args:
        client: KIS REST API 클라이언트
        market: 거래소 코드 (기본값: "NAS" - 나스닥)
                미국: NAS(나스닥), NYS(뉴욕), AMS(아멕스)
                미국주간: BAQ(나스닥), BAY(뉴욕), BAA(아멕스)
                아시아: HKS(홍콩), TSE(도쿄), SHS(상해), SZS(심천)
                베트남: HSX(호치민), HNX(하노이)

    Raises:
        ValueError: 유효하지 않은 거래소 코드인 경우
    """

    def __init__(self, client: KISRestClient, *, market: str = "NAS") -> None:
        self.client = client
        # 거래소 코드 정규화
        market_upper = market.upper()
        self.market = EXCHANGE_CODES.get(market_upper, market_upper)

        # 유효한 거래소 코드인지 검증
        if self.market not in VALID_EXCHANGE_CODES:
            valid_codes = ", ".join(sorted(VALID_EXCHANGE_CODES))
            raise ValueError(
                f"유효하지 않은 거래소 코드입니다: {market}. "
                f"유효한 코드: {valid_codes}"
            )

    def _validate_symbol(self, symbol: str) -> str:
        """심볼을 검증하고 정규화합니다."""
        normalized = (symbol or "").strip().upper()
        if not normalized:
            raise ValueError("symbol은 비어 있을 수 없습니다.")
        return normalized

    def _build_params(self, symbol: str) -> Dict[str, Any]:
        """API 요청 파라미터를 구성합니다."""
        return {
            "AUTH": "",  # 사용자권한정보 (빈 값)
            "EXCD": self.market,  # 거래소코드
            "SYMB": symbol,  # 종목코드
        }

    def get_quote(self, symbol: str) -> Quote:
        """해외주식 현재가를 조회합니다.

        Args:
            symbol: 종목 심볼 (예: "AAPL", "MSFT")

        Returns:
            Quote: 현재가 정보

        Raises:
            ValueError: 심볼이 없거나 API 호출 실패 시
        """
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
            # KIS API 응답 필드 매핑 (v1_해외주식-009)
            # last: 현재가, base: 전일종가, diff: 대비(절대값), rate: 등락율
            # sign: 대비기호 (1:상한, 2:상승, 3:보합, 4:하한, 5:하락)
            # tvol: 거래량
            last_raw = output.get("last") or "0"
            base_raw = output.get("base")  # None이면 폴백 처리
            diff_raw = output.get("diff") or "0"
            rate_raw = output.get("rate") or "0"
            sign_raw = output.get("sign") or "3"  # 기본값: 보합
            tvol_raw = output.get("tvol")

            last = float(last_raw) if last_raw else 0.0
            # base가 없거나 빈 값이면 last 사용
            prev_close = float(base_raw) if base_raw else last
            diff_abs = float(diff_raw) if diff_raw else 0.0

            # sign에 따라 부호 적용 (4, 5는 하락 → 음수)
            sign = str(sign_raw).strip()
            change = -diff_abs if sign in ("4", "5") else diff_abs

            # rate는 이미 부호가 포함되어 있음 (+0.65, -1.21 등)
            # + 기호 제거 후 float 변환
            rate_str = str(rate_raw).replace("+", "") if rate_raw else "0"
            change_rate = float(rate_str) if rate_str else 0.0

            volume = int(float(tvol_raw)) if tvol_raw not in (None, "", "0") else None

            logger.debug(
                "Quote for %s: last=%.2f, base=%.2f, diff=%.2f (sign=%s), rate=%.2f%%, vol=%s",
                symbol_norm, last, prev_close, change, sign, change_rate, volume
            )

        except (KeyError, ValueError, TypeError) as exc:
            logger.error("KIS 시세 응답 파싱 실패: %s, output=%s", symbol_norm, output)
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
