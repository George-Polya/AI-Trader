"""KIS 계좌 및 체결 조회 서비스."""

from __future__ import annotations

import logging
from datetime import datetime
from typing import TYPE_CHECKING, List, Optional, Tuple

from models.broker import BalanceLine, Execution

if TYPE_CHECKING:
    from integrations.kis_client import KISRestClient
    from integrations.kis_settings import KISSettings


logger = logging.getLogger(__name__)


class KISAccountService:
    """KIS 계좌 잔고 및 체결 내역 조회 서비스."""

    def __init__(self, client: KISRestClient, settings: KISSettings) -> None:
        self._client = client
        self._settings = settings
        # 기본적으로 모의투자 계좌/상품 코드를 사용 (실전 전환 시 분기 필요)
        self._cano = settings.my_paper_stock
        self._acnt_prdt_cd = settings.my_prod
        self._currency = "USD"  # 기본 통화
        self._excg_cd = "NASD"  # 기본 거래소

    def _normalize_date_range(
        self, start_date: Optional[str], end_date: Optional[str]
    ) -> Tuple[str, str]:
        """날짜 범위를 검증하고 기본값(최근 1일)을 설정합니다."""
        today = datetime.now().strftime("%Y%m%d")

        if not start_date and not end_date:
            return today, today

        if not start_date:
            start_date = today
        if not end_date:
            end_date = today

        try:
            s_dt = datetime.strptime(start_date, "%Y%m%d")
            e_dt = datetime.strptime(end_date, "%Y%m%d")
        except ValueError as exc:
            raise ValueError(f"Date format must be YYYYMMDD: {start_date} ~ {end_date}") from exc

        if s_dt > e_dt:
            raise ValueError(f"start_date must be less than or equal to end_date: {start_date} > {end_date}")

        return start_date, end_date

    def get_balance(self) -> List[BalanceLine]:
        """보유 잔고를 조회합니다."""
        path = "/uapi/overseas-stock/v1/trading/inquire-balance"
        params = {
            "CANO": self._cano,
            "ACNT_PRDT_CD": self._acnt_prdt_cd,
            "OVRS_EXCG_CD": self._excg_cd,
            "TR_CRCY_CD": self._currency,
            "CTX_AREA_FK100": "",
            "CTX_AREA_NK100": "",
            "CTX_AREA_BR100": "",
        }

        try:
            resp = self._client.request("GET", path, tr_id="VTTS3012R", params=params)
        except Exception as exc:
            logger.error(f"KIS balance check failed: {exc}")
            raise

        # 페이징 결과 정규화
        if isinstance(resp, dict):
            pages = [resp]
        else:
            pages = resp

        balance_lines: List[BalanceLine] = []
        for page in pages:
            output1 = page.get("output1", [])
            if not output1:
                continue

            for item in output1:
                try:
                    symbol = item["ovrs_pdno"]
                    qty = int(item["ovrs_cblc_qty"])
                    # 잔고 수량이 0이면 건너뜀 (옵션에 따라 다를 수 있음)
                    if qty <= 0:
                        continue

                    value = float(item["ovrs_stck_evlu_amt"])
                    line = BalanceLine(
                        symbol=symbol,
                        qty=qty,
                        value=value,
                        currency=self._currency,
                        raw=item,
                    )
                    balance_lines.append(line)
                except (KeyError, ValueError) as e:
                    logger.error(f"Failed to parse balance item: {item} -> {e}")
                    raise RuntimeError(f"Balance parsing failed for item: {item}") from e

        return balance_lines

    def get_fills(
        self, start_date: Optional[str] = None, end_date: Optional[str] = None
    ) -> List[Execution]:
        """체결 내역을 조회합니다."""
        s_dt, e_dt = self._normalize_date_range(start_date, end_date)
        path = "/uapi/overseas-stock/v1/trading/inquire-ccnl"
        params = {
            "CANO": self._cano,
            "ACNT_PRDT_CD": self._acnt_prdt_cd,
            "PDNO": "%",
            "ORD_STRT_DT": s_dt,
            "ORD_END_DT": e_dt,
            "SLL_BUY_DVSN": "00",  # 전체
            "CCLD_NCCS_DVSN": "00",  # 전체
            "OVRS_EXCG_CD": self._excg_cd,
            "CTX_AREA_FK100": "",
            "CTX_AREA_NK100": "",
            "CTX_AREA_BR100": "",
        }

        try:
            resp = self._client.request("GET", path, tr_id="VTTS5012R", params=params)
        except Exception as exc:
            logger.error(f"KIS fills check failed: {exc}")
            raise

        if isinstance(resp, dict):
            pages = [resp]
        else:
            pages = resp

        executions: List[Execution] = []
        for page in pages:
            # API 문서에 따라 output 또는 output1을 사용.
            # 통상 체결내역은 output 리스트에 담김.
            # 여기서는 output을 우선 확인.
            items = page.get("output", [])
            if not items:
                # output이 없으면 output1 시도 (구조에 따라 다름)
                items = page.get("output1", [])

            for item in items:
                try:
                    # item 구조 예:
                    # pdno: 종목번호
                    # ft_ccld_qty: 체결수량 (문자열일 수 있음)
                    # ft_ccld_unpr3: 체결단가
                    # prcs_stat_name: 처리상태명 (체결 등)
                    # sll_buy_dvsn_cd_name: 매도매수구분
                    # odno: 주문번호
                    # ord_dt: 주문일자
                    # ord_tmd: 주문시각

                    symbol = item.get("pdno")
                    if not symbol:  # 가끔 합계 데이터가 들어올 수 있음
                        continue

                    qty_str = item.get("ft_ccld_qty", "0")
                    qty = int(float(qty_str))  # 소수점 가능성 대비

                    price_str = item.get("ft_ccld_unpr3", "0")
                    price = float(price_str)

                    status = item.get("prcs_stat_name", "Unknown")
                    side = item.get("sll_buy_dvsn_cd_name", "Unknown")
                    order_no = item.get("odno", "")

                    # filled_at 구성
                    ord_dt = item.get("ord_dt", "")
                    ord_tmd = item.get("ord_tmd", "")
                    filled_at = f"{ord_dt} {ord_tmd}".strip()

                    exec_obj = Execution(
                        symbol=symbol,
                        qty=qty,
                        price=price,
                        status=status,
                        side=side,
                        order_no=order_no,
                        filled_at=filled_at,
                        raw=item,
                    )
                    executions.append(exec_obj)
                except (KeyError, ValueError) as e:
                    logger.error(f"Failed to parse execution item: {item} -> {e}")
                    raise RuntimeError(f"Execution parsing failed for item: {item}") from e

        return executions

    def get_cash_balance(self) -> float:
        """해외주식 매수 가능 금액(예수금)을 조회합니다."""
        # 모의투자: VTTS3007R, 실전: TTTS3007R (나중에 분기 필요)
        # 일단 모의투자 기준 TR ID 사용
        tr_id = "VTTS3007R"
        path = "/uapi/overseas-stock/v1/trading/inquire-psbl-order"
        
        params = {
            "CANO": self._cano,
            "ACNT_PRDT_CD": self._acnt_prdt_cd,
            "OVRS_EXCG_CD": self._excg_cd, # NASD
            "OVRS_ORD_UNPR": "0", # 시장가 조회를 위해 0 또는 현재가
            "ITEM_CD": "", # 종목코드 (필수 아님, 빈 문자열)
        }

        try:
            resp = self._client.request("GET", path, tr_id=tr_id, params=params, paginate=False)
        except Exception as exc:
            logger.error(f"KIS cash balance check failed: {exc}")
            # 실패 시 0.0 반환 또는 에러 전파. 여기선 안전하게 에러 로깅 후 0.0
            return 0.0
            
        # resp가 리스트일 수도 있고 딕셔너리일 수도 있음 (Client 구현상 단일 페이지면 딕셔너리)
        if isinstance(resp, list):
            resp = resp[0]
            
        output = resp.get("output", {})
        # "ord_psbl_frcr_amt": 주문가능외화금액 (USD)
        # "frcr_drwg_psbl_amt": 외화출금가능금액
        # 여기서는 매수 가능 금액인 ord_psbl_frcr_amt를 사용
        cash_str = output.get("ord_psbl_frcr_amt", "0")
        
        try:
            return float(cash_str)
        except ValueError:
            logger.error(f"Failed to parse cash amount: {cash_str}")
            return 0.0