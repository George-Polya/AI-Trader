"""KIS WebSocket 클라이언트 모듈.

실시간 시세 및 체결 통보를 위한 WebSocket 클라이언트를 제공한다.
"""

from __future__ import annotations

import asyncio
import json
import logging
from abc import ABC, abstractmethod
from base64 import b64decode
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from io import StringIO
from typing import Any, Callable, Optional, Protocol

import pandas as pd
import requests
import websockets
from Crypto.Cipher import AES
from Crypto.Util.Padding import unpad
from websockets.exceptions import ConnectionClosed

from integrations.kis_settings import KISSettings, load_kis_settings

logger = logging.getLogger(__name__)

# Lazy import to avoid circular dependency
_execution_handler = None


def _get_execution_handler():
    """체결 핸들러 싱글톤 인스턴스."""
    global _execution_handler
    if _execution_handler is None:
        from integrations.kis_execution_handler import (
            create_execution_handler_from_config,
            notify_agent_execution,
        )
        handler = create_execution_handler_from_config()
        # 에이전트 알림 콜백 등록
        handler.add_callback(notify_agent_execution)
        _execution_handler = handler
    return _execution_handler


# =============================================================================
# Data Classes & Enums
# =============================================================================


class SubscriptionType(str, Enum):
    """구독 타입."""

    REGISTER = "1"  # 등록
    UNREGISTER = "2"  # 해제


class MarketType(str, Enum):
    """해외 시장 구분."""

    NYSE = "NYS"  # 뉴욕
    NASDAQ = "NAS"  # 나스닥
    AMEX = "AMS"  # 아멕스
    HONGKONG = "HKS"  # 홍콩
    SHANGHAI = "SHS"  # 상해
    SHENZHEN = "SZS"  # 심천
    TOKYO = "TSE"  # 도쿄
    HANOI = "HNX"  # 하노이
    HOCHIMINH = "HSX"  # 호치민


@dataclass
class RealtimeTick:
    """실시간 체결 데이터."""

    symbol: str
    price: float
    volume: int
    timestamp: datetime
    change: float = 0.0
    change_rate: float = 0.0
    side: str = ""  # "buy" or "sell"
    open_price: float = 0.0
    high_price: float = 0.0
    low_price: float = 0.0
    total_volume: int = 0
    total_amount: float = 0.0


@dataclass
class RealtimeQuote:
    """실시간 호가 데이터."""

    symbol: str
    timestamp: datetime
    bid_price: float = 0.0
    ask_price: float = 0.0
    bid_volume: int = 0
    ask_volume: int = 0


@dataclass
class ExecutionNotice:
    """체결 통보 데이터."""

    order_no: str
    symbol: str
    side: str  # "buy" or "sell"
    quantity: int
    price: float
    executed_qty: int
    executed_price: float
    timestamp: datetime
    account_no: str = ""
    is_executed: bool = False
    is_accepted: bool = False


@dataclass
class SubscriptionInfo:
    """구독 정보."""

    tr_id: str
    tr_key: str
    columns: list[str] = field(default_factory=list)
    encrypt: str = "N"
    iv: Optional[str] = None
    key: Optional[str] = None


# =============================================================================
# Callback Protocols
# =============================================================================


class OnTickCallback(Protocol):
    """실시간 체결 콜백."""

    def __call__(self, tick: RealtimeTick) -> None:
        ...


class OnQuoteCallback(Protocol):
    """실시간 호가 콜백."""

    def __call__(self, quote: RealtimeQuote) -> None:
        ...


class OnExecutionCallback(Protocol):
    """체결 통보 콜백."""

    def __call__(self, execution: ExecutionNotice) -> None:
        ...


class OnRawDataCallback(Protocol):
    """Raw 데이터 콜백."""

    def __call__(self, tr_id: str, df: pd.DataFrame) -> None:
        ...


# =============================================================================
# WebSocket Authenticator (Subtask 8.1)
# =============================================================================


class KISWebSocketAuthenticator:
    """KIS WebSocket 승인키 발급 클래스.

    WebSocket 연결에 필요한 approval_key를 발급받는다.
    """

    API_URL = "/oauth2/Approval"

    def __init__(self, settings: KISSettings, *, is_paper: bool = True) -> None:
        """초기화.

        Args:
            settings: KIS 설정 객체
            is_paper: 모의투자 여부 (기본값: True)
        """
        self._settings = settings
        self._is_paper = is_paper
        self._approval_key: Optional[str] = None
        self._issued_at: Optional[datetime] = None

    @property
    def base_url(self) -> str:
        """REST API 기본 URL."""
        return self._settings.vps if self._is_paper else self._settings.prod

    @property
    def approval_key(self) -> Optional[str]:
        """현재 승인키."""
        return self._approval_key

    def get_credentials(self) -> tuple[str, str]:
        """앱키와 앱시크릿 반환."""
        if self._is_paper:
            return self._settings.paper_app, self._settings.paper_sec
        return self._settings.my_app or "", self._settings.my_sec or ""

    def issue_approval_key(self) -> str:
        """WebSocket 접속용 승인키 발급.

        Returns:
            발급된 approval_key

        Raises:
            RuntimeError: 승인키 발급 실패 시
        """
        appkey, appsecret = self.get_credentials()

        url = f"{self.base_url}{self.API_URL}"
        headers = {
            "Content-Type": "application/json",
            "Accept": "text/plain",
            "charset": "UTF-8",
        }
        data = {
            "grant_type": "client_credentials",
            "appkey": appkey,
            "secretkey": appsecret,
        }

        try:
            response = requests.post(url, data=json.dumps(data), headers=headers, timeout=10)
            response.raise_for_status()

            result = response.json()
            self._approval_key = result.get("approval_key")
            self._issued_at = datetime.now()

            if not self._approval_key:
                raise RuntimeError("승인키가 응답에 포함되지 않았습니다.")

            logger.info("WebSocket 승인키 발급 성공")
            return self._approval_key

        except requests.RequestException as e:
            logger.error("WebSocket 승인키 발급 실패: %s", e)
            raise RuntimeError(f"WebSocket 승인키 발급 실패: {e}") from e

    def ensure_approval_key(self) -> str:
        """승인키가 없으면 발급, 있으면 기존 키 반환."""
        if self._approval_key is None:
            return self.issue_approval_key()
        return self._approval_key

    def refresh_approval_key(self) -> str:
        """승인키 강제 재발급."""
        self._approval_key = None
        return self.issue_approval_key()


# =============================================================================
# Message Parser & Crypto Utils
# =============================================================================


def aes_cbc_base64_dec(key: str, iv: str, cipher_text: str) -> str:
    """AES CBC 복호화.

    Args:
        key: 복호화 키
        iv: 초기화 벡터
        cipher_text: 암호화된 텍스트 (Base64 인코딩)

    Returns:
        복호화된 문자열
    """
    cipher = AES.new(key.encode("utf-8"), AES.MODE_CBC, iv.encode("utf-8"))
    decrypted = unpad(cipher.decrypt(b64decode(cipher_text)), AES.block_size)
    return decrypted.decode("utf-8")


@dataclass
class SystemMessage:
    """시스템 메시지 파싱 결과."""

    is_ok: bool = False
    tr_id: str = ""
    tr_key: str = ""
    is_unsub: bool = False
    is_pingpong: bool = False
    message: str = ""
    iv: Optional[str] = None
    key: Optional[str] = None
    encrypt: str = "N"


def parse_system_message(data: str) -> SystemMessage:
    """시스템 메시지 파싱.

    Args:
        data: 수신된 JSON 문자열

    Returns:
        파싱된 SystemMessage
    """
    result = SystemMessage()

    try:
        rdic = json.loads(data)
    except json.JSONDecodeError:
        return result

    result.tr_id = rdic.get("header", {}).get("tr_id", "")

    if result.tr_id != "PINGPONG":
        result.tr_key = rdic.get("header", {}).get("tr_key", "")
        result.encrypt = rdic.get("header", {}).get("encrypt", "N")

    body = rdic.get("body")
    if body is not None:
        result.is_ok = body.get("rt_cd") == "0"
        result.message = body.get("msg1", "")

        # 복호화 키 추출
        output = body.get("output", {})
        if output:
            result.iv = output.get("iv")
            result.key = output.get("key")

        result.is_unsub = result.message.startswith("UNSUB")
    else:
        result.is_pingpong = result.tr_id == "PINGPONG"

    return result


# =============================================================================
# TR ID Constants
# =============================================================================


class OverseasStockTRID:
    """해외주식 TR ID 상수."""

    # 실시간 체결가 (지연/무료)
    REALTIME_QUOTE = "HDFSCNT0"
    # 실시간 호가
    REALTIME_ORDERBOOK = "HDFSASP0"
    # 지연 호가 (아시아)
    DELAYED_ORDERBOOK_ASIA = "HDFSASP1"
    # 체결 통보 (실전)
    EXECUTION_NOTICE_REAL = "H0GSCNI0"
    # 체결 통보 (모의)
    EXECUTION_NOTICE_DEMO = "H0GSCNI9"


class DomesticStockTRID:
    """국내주식 TR ID 상수."""

    # 실시간 체결가 (KRX)
    REALTIME_QUOTE_KRX = "H0STCNT0"
    # 실시간 호가 (KRX)
    REALTIME_ORDERBOOK_KRX = "H0STASP0"
    # 체결 통보 (실전)
    EXECUTION_NOTICE_REAL = "H0STCNI0"
    # 체결 통보 (모의)
    EXECUTION_NOTICE_DEMO = "H0STCNI9"


# =============================================================================
# Column Definitions
# =============================================================================


OVERSEAS_QUOTE_COLUMNS = [
    "SYMB",  # 종목코드
    "ZDIV",  # 소수점 자릿수
    "TYMD",  # 현지 영업일자
    "XYMD",  # 현지 일자
    "XHMS",  # 현지 시간
    "KYMD",  # 한국 일자
    "KHMS",  # 한국 시간
    "OPEN",  # 시가
    "HIGH",  # 고가
    "LOW",  # 저가
    "LAST",  # 현재가
    "SIGN",  # 대비부호
    "DIFF",  # 전일대비
    "RATE",  # 등락률
    "PBID",  # 매수호가
    "PASK",  # 매도호가
    "VBID",  # 매수잔량
    "VASK",  # 매도잔량
    "EVOL",  # 체결량
    "TVOL",  # 거래량
    "TAMT",  # 거래대금
    "BIVL",  # 매수체결량
    "ASVL",  # 매도체결량
    "STRN",  # 체결강도
    "MTYP",  # 시장구분
]

OVERSEAS_ORDERBOOK_COLUMNS = [
    "symb",  # 종목코드
    "zdiv",  # 소수점 자릿수
    "xymd",  # 현지 일자
    "xhms",  # 현지 시간
    "kymd",  # 한국 일자
    "khms",  # 한국 시간
    "bvol",  # 매수총잔량
    "avol",  # 매도총잔량
    "bdvl",  # 매수총잔량대비
    "advl",  # 매도총잔량대비
    "pbid1",  # 매수호가1
    "pask1",  # 매도호가1
    "vbid1",  # 매수잔량1
    "vask1",  # 매도잔량1
    "dbid1",  # 매수잔량대비1
    "dask1",  # 매도잔량대비1
]

OVERSEAS_EXECUTION_COLUMNS = [
    "CUST_ID",  # 고객ID
    "ACNT_NO",  # 계좌번호
    "ODER_NO",  # 주문번호
    "OODER_NO",  # 원주문번호
    "SELN_BYOV_CLS",  # 매도매수구분
    "RCTF_CLS",  # 정정취소구분
    "ODER_KIND2",  # 주문종류2
    "STCK_SHRN_ISCD",  # 종목코드
    "CNTG_QTY",  # 체결수량
    "CNTG_UNPR",  # 체결단가
    "STCK_CNTG_HOUR",  # 체결시간
    "RFUS_YN",  # 거부여부
    "CNTG_YN",  # 체결여부
    "ACPT_YN",  # 접수여부
    "BRNC_NO",  # 지점번호
    "ODER_QTY",  # 주문수량
    "ACNT_NAME",  # 계좌명
    "CNTG_ISNM",  # 체결종목명
    "ODER_COND",  # 주문조건
    "DEBT_GB",  # 신용구분
    "DEBT_DATE",  # 신용일자
    "START_TM",  # 시작시간
    "END_TM",  # 종료시간
    "TM_DIV_TP",  # 시간구분
]


# =============================================================================
# Subscription Manager
# =============================================================================


class SubscriptionManager:
    """구독 관리자."""

    def __init__(self) -> None:
        self._subscriptions: dict[str, SubscriptionInfo] = {}

    def add(self, tr_id: str, tr_key: str, columns: list[str]) -> SubscriptionInfo:
        """구독 추가."""
        key = f"{tr_id}:{tr_key}"
        info = SubscriptionInfo(tr_id=tr_id, tr_key=tr_key, columns=columns)
        self._subscriptions[key] = info
        return info

    def get(self, tr_id: str, tr_key: str = "") -> Optional[SubscriptionInfo]:
        """구독 정보 조회."""
        key = f"{tr_id}:{tr_key}"
        return self._subscriptions.get(key)

    def get_by_tr_id(self, tr_id: str) -> Optional[SubscriptionInfo]:
        """TR_ID로 구독 정보 조회."""
        for key, info in self._subscriptions.items():
            if info.tr_id == tr_id:
                return info
        return None

    def update_crypto(self, tr_id: str, encrypt: str, iv: Optional[str], key: Optional[str]) -> None:
        """암호화 정보 업데이트."""
        for info in self._subscriptions.values():
            if info.tr_id == tr_id:
                info.encrypt = encrypt
                info.iv = iv
                info.key = key
                break

    def remove(self, tr_id: str, tr_key: str) -> bool:
        """구독 제거."""
        key = f"{tr_id}:{tr_key}"
        if key in self._subscriptions:
            del self._subscriptions[key]
            return True
        return False

    def clear(self) -> None:
        """모든 구독 제거."""
        self._subscriptions.clear()

    def get_all_keys(self) -> list[str]:
        """모든 구독 키 반환."""
        return list(self._subscriptions.keys())

    def count(self) -> int:
        """구독 개수."""
        return len(self._subscriptions)


# =============================================================================
# KIS WebSocket Client (Subtasks 8.2 ~ 8.5)
# =============================================================================


class KISWebSocketClient:
    """KIS 실시간 시세 WebSocket 클라이언트.

    해외주식 실시간 시세 및 체결 통보를 수신한다.
    """

    MAX_SUBSCRIPTIONS = 40
    WEBSOCKET_PATH = "/tryitout/H0GSCNT0"  # 해외주식용

    def __init__(
        self,
        settings: Optional[KISSettings] = None,
        *,
        is_paper: bool = True,
        on_tick: Optional[OnTickCallback] = None,
        on_quote: Optional[OnQuoteCallback] = None,
        on_execution: Optional[OnExecutionCallback] = None,
        on_raw_data: Optional[OnRawDataCallback] = None,
        reconnect_interval: float = 5.0,
        heartbeat_timeout: float = 60.0,
        max_retries: int = 5,
    ) -> None:
        """초기화.

        Args:
            settings: KIS 설정 객체 (None이면 자동 로드)
            is_paper: 모의투자 여부 (기본값: True)
            on_tick: 실시간 체결 콜백
            on_quote: 실시간 호가 콜백
            on_execution: 체결 통보 콜백
            on_raw_data: Raw 데이터 콜백
            reconnect_interval: 재연결 간격 (초)
            heartbeat_timeout: 하트비트 타임아웃 (초)
            max_retries: 최대 재시도 횟수
        """
        self._settings = settings or load_kis_settings()
        self._is_paper = is_paper
        self._authenticator = KISWebSocketAuthenticator(self._settings, is_paper=is_paper)

        # 콜백
        self._on_tick = on_tick
        self._on_quote = on_quote
        self._on_execution = on_execution
        self._on_raw_data = on_raw_data

        # 연결 설정
        self._reconnect_interval = reconnect_interval
        self._heartbeat_timeout = heartbeat_timeout
        self._max_retries = max_retries

        # 내부 상태
        self._ws: Optional[websockets.WebSocketClientProtocol] = None
        self._running = False
        self._retry_count = 0
        self._subscription_manager = SubscriptionManager()
        self._pending_subscriptions: list[tuple[str, str, list[str], dict]] = []
        self._last_heartbeat: datetime = datetime.now()

    @property
    def ws_url(self) -> str:
        """WebSocket URL."""
        base = self._settings.vops if self._is_paper else self._settings.ops
        return f"{base}{self.WEBSOCKET_PATH}"

    @property
    def is_connected(self) -> bool:
        """연결 상태."""
        return self._ws is not None and self._ws.open

    @property
    def subscription_count(self) -> int:
        """현재 구독 개수."""
        return self._subscription_manager.count()

    # -------------------------------------------------------------------------
    # Connection Management (Subtask 8.2)
    # -------------------------------------------------------------------------

    async def connect(self) -> None:
        """WebSocket 연결 수립."""
        # 승인키 발급
        approval_key = self._authenticator.ensure_approval_key()
        logger.info("WebSocket 연결 시도: %s", self.ws_url)

        try:
            self._ws = await websockets.connect(
                self.ws_url,
                ping_interval=None,  # 자체 핑퐁 처리
                ping_timeout=None,
            )
            self._running = True
            self._retry_count = 0
            self._last_heartbeat = datetime.now()
            logger.info("WebSocket 연결 성공")

        except Exception as e:
            logger.error("WebSocket 연결 실패: %s", e)
            raise

    async def disconnect(self) -> None:
        """WebSocket 연결 종료."""
        self._running = False
        if self._ws:
            await self._ws.close()
            self._ws = None
        logger.info("WebSocket 연결 종료")

    # -------------------------------------------------------------------------
    # Subscription Methods (Subtask 8.3)
    # -------------------------------------------------------------------------

    def _build_subscription_message(
        self,
        tr_id: str,
        tr_key: str,
        tr_type: SubscriptionType,
    ) -> dict[str, Any]:
        """구독 메시지 생성."""
        approval_key = self._authenticator.ensure_approval_key()

        return {
            "header": {
                "approval_key": approval_key,
                "custtype": "P",
                "tr_type": tr_type.value,
                "content-type": "utf-8",
            },
            "body": {
                "input": {
                    "tr_id": tr_id,
                    "tr_key": tr_key,
                }
            },
        }

    async def _send_subscription(
        self,
        tr_id: str,
        tr_key: str,
        tr_type: SubscriptionType,
        columns: list[str],
    ) -> None:
        """구독 메시지 전송."""
        if not self.is_connected:
            raise RuntimeError("WebSocket이 연결되지 않았습니다.")

        if tr_type == SubscriptionType.REGISTER:
            if self._subscription_manager.count() >= self.MAX_SUBSCRIPTIONS:
                raise RuntimeError(f"최대 구독 개수({self.MAX_SUBSCRIPTIONS})를 초과했습니다.")
            self._subscription_manager.add(tr_id, tr_key, columns)

        msg = self._build_subscription_message(tr_id, tr_key, tr_type)
        await self._ws.send(json.dumps(msg))
        logger.info("구독 메시지 전송: tr_id=%s, tr_key=%s, type=%s", tr_id, tr_key, tr_type.value)

        # Rate limiting
        await asyncio.sleep(0.1)

    async def subscribe_quote(
        self,
        symbol: str,
        market: MarketType = MarketType.NASDAQ,
    ) -> None:
        """해외주식 실시간 체결가 구독.

        Args:
            symbol: 종목코드 (예: AAPL)
            market: 시장 구분 (기본값: NASDAQ)
        """
        tr_key = f"D{market.value}{symbol}"
        await self._send_subscription(
            OverseasStockTRID.REALTIME_QUOTE,
            tr_key,
            SubscriptionType.REGISTER,
            OVERSEAS_QUOTE_COLUMNS,
        )

    async def subscribe_orderbook(
        self,
        symbol: str,
        market: MarketType = MarketType.NASDAQ,
    ) -> None:
        """해외주식 실시간 호가 구독.

        Args:
            symbol: 종목코드 (예: AAPL)
            market: 시장 구분 (기본값: NASDAQ)
        """
        tr_key = f"D{market.value}{symbol}"
        await self._send_subscription(
            OverseasStockTRID.REALTIME_ORDERBOOK,
            tr_key,
            SubscriptionType.REGISTER,
            OVERSEAS_ORDERBOOK_COLUMNS,
        )

    async def unsubscribe_quote(
        self,
        symbol: str,
        market: MarketType = MarketType.NASDAQ,
    ) -> None:
        """해외주식 실시간 체결가 구독 해제."""
        tr_key = f"D{market.value}{symbol}"
        await self._send_subscription(
            OverseasStockTRID.REALTIME_QUOTE,
            tr_key,
            SubscriptionType.UNREGISTER,
            [],
        )
        self._subscription_manager.remove(OverseasStockTRID.REALTIME_QUOTE, tr_key)

    async def unsubscribe_orderbook(
        self,
        symbol: str,
        market: MarketType = MarketType.NASDAQ,
    ) -> None:
        """해외주식 실시간 호가 구독 해제."""
        tr_key = f"D{market.value}{symbol}"
        await self._send_subscription(
            OverseasStockTRID.REALTIME_ORDERBOOK,
            tr_key,
            SubscriptionType.UNREGISTER,
            [],
        )
        self._subscription_manager.remove(OverseasStockTRID.REALTIME_ORDERBOOK, tr_key)

    # -------------------------------------------------------------------------
    # Execution Notice (Subtask 8.4)
    # -------------------------------------------------------------------------

    async def subscribe_execution_notice(self, hts_id: str) -> None:
        """해외주식 체결 통보 구독.

        Args:
            hts_id: HTS ID
        """
        tr_id = (
            OverseasStockTRID.EXECUTION_NOTICE_DEMO
            if self._is_paper
            else OverseasStockTRID.EXECUTION_NOTICE_REAL
        )
        await self._send_subscription(
            tr_id,
            hts_id,
            SubscriptionType.REGISTER,
            OVERSEAS_EXECUTION_COLUMNS,
        )

    async def unsubscribe_execution_notice(self, hts_id: str) -> None:
        """해외주식 체결 통보 구독 해제."""
        tr_id = (
            OverseasStockTRID.EXECUTION_NOTICE_DEMO
            if self._is_paper
            else OverseasStockTRID.EXECUTION_NOTICE_REAL
        )
        await self._send_subscription(
            tr_id,
            hts_id,
            SubscriptionType.UNREGISTER,
            [],
        )
        self._subscription_manager.remove(tr_id, hts_id)

    def _parse_execution_notice(self, df: pd.DataFrame) -> Optional[ExecutionNotice]:
        """체결 통보 데이터 파싱."""
        if df.empty:
            return None

        row = df.iloc[0]
        try:
            return ExecutionNotice(
                order_no=str(row.get("ODER_NO", "")),
                symbol=str(row.get("STCK_SHRN_ISCD", "")),
                side="buy" if row.get("SELN_BYOV_CLS") == "02" else "sell",
                quantity=int(row.get("ODER_QTY", 0)),
                price=float(row.get("CNTG_UNPR", 0)),
                executed_qty=int(row.get("CNTG_QTY", 0)),
                executed_price=float(row.get("CNTG_UNPR", 0)),
                timestamp=datetime.now(),
                account_no=str(row.get("ACNT_NO", "")),
                is_executed=row.get("CNTG_YN") == "Y",
                is_accepted=row.get("ACPT_YN") == "Y",
            )
        except Exception as e:
            logger.warning("체결 통보 파싱 실패: %s", e)
            return None

    # -------------------------------------------------------------------------
    # Message Handling (Subtask 8.2)
    # -------------------------------------------------------------------------

    async def _handle_message(self, data: str) -> None:
        """수신 메시지 처리."""
        self._last_heartbeat = datetime.now()

        # 데이터 메시지인 경우 (0 또는 1로 시작)
        if data[0] in ("0", "1"):
            await self._handle_data_message(data)
        else:
            await self._handle_system_message(data)

    async def _handle_data_message(self, data: str) -> None:
        """데이터 메시지 처리."""
        parts = data.split("|")
        if len(parts) < 4:
            logger.warning("잘못된 데이터 형식: %s", data[:100])
            return

        tr_id = parts[1]
        payload = parts[3]

        # 구독 정보 조회
        sub_info = self._subscription_manager.get_by_tr_id(tr_id)
        if sub_info is None:
            logger.warning("알 수 없는 TR_ID: %s", tr_id)
            return

        # 암호화된 경우 복호화
        if sub_info.encrypt == "Y" and sub_info.key and sub_info.iv:
            try:
                payload = aes_cbc_base64_dec(sub_info.key, sub_info.iv, payload)
            except Exception as e:
                logger.error("복호화 실패: %s", e)
                return

        # DataFrame으로 변환
        try:
            df = pd.read_csv(
                StringIO(payload),
                header=None,
                sep="^",
                names=sub_info.columns,
                dtype=object,
            )
        except Exception as e:
            logger.error("데이터 파싱 실패: %s", e)
            return

        # Raw 데이터 콜백
        if self._on_raw_data:
            self._on_raw_data(tr_id, df)

        # 타입별 콜백 처리
        await self._dispatch_callback(tr_id, df)

    async def _dispatch_callback(self, tr_id: str, df: pd.DataFrame) -> None:
        """TR_ID에 따라 적절한 콜백 호출."""
        if df.empty:
            return

        # 실시간 체결가
        if tr_id == OverseasStockTRID.REALTIME_QUOTE and self._on_tick:
            tick = self._parse_tick(df)
            if tick:
                self._on_tick(tick)

        # 실시간 호가
        elif tr_id == OverseasStockTRID.REALTIME_ORDERBOOK and self._on_quote:
            quote = self._parse_quote(df)
            if quote:
                self._on_quote(quote)

        # 체결 통보
        elif tr_id in (
            OverseasStockTRID.EXECUTION_NOTICE_REAL,
            OverseasStockTRID.EXECUTION_NOTICE_DEMO,
        ):
            await self._handle_execution_notice(df)

    def _parse_tick(self, df: pd.DataFrame) -> Optional[RealtimeTick]:
        """실시간 체결 데이터 파싱."""
        if df.empty:
            return None

        row = df.iloc[0]
        try:
            return RealtimeTick(
                symbol=str(row.get("SYMB", "")),
                price=float(row.get("LAST", 0)),
                volume=int(row.get("EVOL", 0)),
                timestamp=datetime.now(),
                change=float(row.get("DIFF", 0)),
                change_rate=float(row.get("RATE", 0)),
                open_price=float(row.get("OPEN", 0)),
                high_price=float(row.get("HIGH", 0)),
                low_price=float(row.get("LOW", 0)),
                total_volume=int(row.get("TVOL", 0)),
                total_amount=float(row.get("TAMT", 0)),
            )
        except Exception as e:
            logger.warning("체결 데이터 파싱 실패: %s", e)
            return None

    def _parse_quote(self, df: pd.DataFrame) -> Optional[RealtimeQuote]:
        """실시간 호가 데이터 파싱."""
        if df.empty:
            return None

        row = df.iloc[0]
        try:
            return RealtimeQuote(
                symbol=str(row.get("symb", "")),
                timestamp=datetime.now(),
                bid_price=float(row.get("pbid1", 0)),
                ask_price=float(row.get("pask1", 0)),
                bid_volume=int(row.get("vbid1", 0)),
                ask_volume=int(row.get("vask1", 0)),
            )
        except Exception as e:
            logger.warning("호가 데이터 파싱 실패: %s", e)
            return None

    async def _handle_execution_notice(self, df: pd.DataFrame) -> None:
        """체결 통보 처리.

        체결 통보를 파싱하고, 주문 로그 업데이트 및 콜백을 호출한다.

        Args:
            df: 체결 통보 DataFrame
        """
        if df.empty:
            return

        # ExecutionNotice 파싱 (기존 로직)
        execution = self._parse_execution_notice(df)
        if execution is None:
            return

        # DataFrame의 raw 데이터를 딕셔너리로 변환
        row = df.iloc[0]
        raw_data = row.to_dict()

        # 체결 핸들러를 통한 주문 로그 업데이트
        try:
            handler = _get_execution_handler()
            record = handler.handle_execution_notice(raw_data)
            if record:
                logger.info(
                    "체결 통보 처리 완료: %s %s %d주 @ %.2f",
                    record.symbol,
                    record.side,
                    record.executed_qty,
                    record.executed_price,
                )
        except Exception as e:
            logger.error("체결 핸들러 처리 오류: %s", e)

        # 사용자 콜백 호출
        if self._on_execution:
            self._on_execution(execution)

    async def _handle_system_message(self, data: str) -> None:
        """시스템 메시지 처리."""
        sys_msg = parse_system_message(data)

        # PINGPONG 처리
        if sys_msg.is_pingpong:
            await self._handle_pingpong(data)
            return

        # 암호화 키 저장
        if sys_msg.key and sys_msg.iv:
            self._subscription_manager.update_crypto(
                sys_msg.tr_id,
                sys_msg.encrypt,
                sys_msg.iv,
                sys_msg.key,
            )

        if sys_msg.is_ok:
            logger.info("구독 성공: tr_id=%s, msg=%s", sys_msg.tr_id, sys_msg.message)
        else:
            logger.warning("구독 실패: tr_id=%s, msg=%s", sys_msg.tr_id, sys_msg.message)

    # -------------------------------------------------------------------------
    # Heartbeat & Reconnection (Subtask 8.5)
    # -------------------------------------------------------------------------

    async def _handle_pingpong(self, data: str) -> None:
        """PINGPONG 메시지 처리."""
        logger.debug("PINGPONG 수신")
        if self._ws:
            await self._ws.pong(data)
            logger.debug("PONG 전송")

    async def _recv_loop(self) -> None:
        """메시지 수신 루프."""
        while self._running and self._ws:
            try:
                data = await asyncio.wait_for(
                    self._ws.recv(),
                    timeout=self._heartbeat_timeout,
                )
                await self._handle_message(data)

            except asyncio.TimeoutError:
                logger.warning("하트비트 타임아웃, 재연결 시도...")
                await self._reconnect()

            except ConnectionClosed as e:
                logger.warning("WebSocket 연결 종료 (code=%s), 재연결 시도...", e.code)
                await self._reconnect()

            except Exception as e:
                logger.error("메시지 처리 오류: %s", e)

    async def _reconnect(self) -> None:
        """재연결 시도."""
        if not self._running:
            return

        self._retry_count += 1
        if self._retry_count > self._max_retries:
            logger.error("최대 재시도 횟수 초과, 연결 종료")
            self._running = False
            return

        logger.info("재연결 시도 %d/%d...", self._retry_count, self._max_retries)
        await asyncio.sleep(self._reconnect_interval)

        try:
            # 기존 연결 정리
            if self._ws:
                await self._ws.close()
                self._ws = None

            # 승인키 재발급
            self._authenticator.refresh_approval_key()

            # 재연결
            await self.connect()

            # 기존 구독 복구
            await self._restore_subscriptions()

        except Exception as e:
            logger.error("재연결 실패: %s", e)
            await self._reconnect()

    async def _restore_subscriptions(self) -> None:
        """기존 구독 복구."""
        keys = self._subscription_manager.get_all_keys()
        logger.info("구독 복구 시작: %d개", len(keys))

        for key in keys:
            info = self._subscription_manager._subscriptions.get(key)
            if info:
                msg = self._build_subscription_message(
                    info.tr_id,
                    info.tr_key,
                    SubscriptionType.REGISTER,
                )
                await self._ws.send(json.dumps(msg))
                await asyncio.sleep(0.1)

        logger.info("구독 복구 완료")

    # -------------------------------------------------------------------------
    # Main Run Loop
    # -------------------------------------------------------------------------

    async def run(self) -> None:
        """WebSocket 클라이언트 실행."""
        await self.connect()

        # 대기 중인 구독 처리
        for tr_id, tr_key, columns, _ in self._pending_subscriptions:
            await self._send_subscription(tr_id, tr_key, SubscriptionType.REGISTER, columns)
        self._pending_subscriptions.clear()

        # 수신 루프
        await self._recv_loop()

    def start(self) -> None:
        """동기 방식으로 클라이언트 실행."""
        try:
            asyncio.run(self.run())
        except KeyboardInterrupt:
            logger.info("키보드 인터럽트로 종료")

    async def start_async(self) -> None:
        """비동기 방식으로 클라이언트 실행."""
        await self.run()


# =============================================================================
# Cache Integration Helpers (Task 9.2)
# =============================================================================


def create_cache_updating_callback(
    user_callback: Optional[OnTickCallback] = None,
) -> OnTickCallback:
    """캐시 업데이트 기능이 포함된 콜백 생성.

    WebSocket에서 수신한 틱 데이터를 자동으로 캐시에 저장하고,
    사용자 정의 콜백도 함께 호출한다.

    Args:
        user_callback: 사용자 정의 틱 콜백 (옵션)

    Returns:
        캐시 업데이트 기능이 포함된 콜백 함수

    Example:
        >>> client = KISWebSocketClient(
        ...     on_tick=create_cache_updating_callback(my_callback)
        ... )
    """
    from integrations.kis_quote_cache import get_quote_cache

    def callback(tick: RealtimeTick) -> None:
        # 캐시 업데이트
        cache = get_quote_cache()
        cache.update(
            symbol=tick.symbol,
            price=tick.price,
            source="websocket",
            volume=tick.total_volume,
            change=tick.change,
            change_rate=tick.change_rate,
            open_price=tick.open_price,
            high_price=tick.high_price,
            low_price=tick.low_price,
        )

        # 사용자 콜백 호출
        if user_callback is not None:
            user_callback(tick)

    return callback


def on_tick_update_cache(tick: RealtimeTick) -> None:
    """WebSocket 틱 수신 시 캐시 업데이트.

    단독 콜백으로 사용하거나, 직접 호출하여 캐시를 업데이트한다.

    Args:
        tick: 실시간 체결 데이터

    Example:
        >>> client = KISWebSocketClient(on_tick=on_tick_update_cache)
    """
    from integrations.kis_quote_cache import get_quote_cache

    cache = get_quote_cache()
    cache.update(
        symbol=tick.symbol,
        price=tick.price,
        source="websocket",
        volume=tick.total_volume,
        change=tick.change,
        change_rate=tick.change_rate,
        open_price=tick.open_price,
        high_price=tick.high_price,
        low_price=tick.low_price,
    )


# =============================================================================
# WebSocket Manager (USE_WEBSOCKET=true 모드용)
# =============================================================================

# NYSE 종목 목록 (대표적인 종목들)
_NYSE_SYMBOLS = {
    "IBM", "JPM", "V", "MA", "UNH", "JNJ", "WMT", "PG", "HD", "DIS",
    "VZ", "KO", "PFE", "MRK", "CVX", "XOM", "BA", "MMM", "CAT", "GS",
    "AXP", "TRV", "DOW", "HON", "NKE", "MCD", "CRM", "ORCL", "ACN", "ABT",
    "TMO", "DHR", "LLY", "BMY", "ABBV", "AMGN", "MDT", "ISRG", "SYK", "BDX",
}


def detect_market(symbol: str) -> MarketType:
    """심볼로부터 시장 타입을 추론.

    NYSE 대표 종목은 NYSE로, 나머지는 NASDAQ으로 분류.
    정확한 분류가 필요하면 종목 마스터 데이터 조회 필요.

    Args:
        symbol: 종목 심볼 (예: "AAPL", "IBM")

    Returns:
        MarketType: NYSE 또는 NASDAQ
    """
    if symbol.upper() in _NYSE_SYMBOLS:
        return MarketType.NYSE
    return MarketType.NASDAQ


# 싱글톤 인스턴스 관리
_ws_manager: Optional["KISWebSocketManager"] = None
_ws_manager_lock = asyncio.Lock()


async def get_websocket_manager() -> "KISWebSocketManager":
    """WebSocket 매니저 싱글톤 인스턴스 반환.

    Returns:
        KISWebSocketManager: 싱글톤 인스턴스
    """
    global _ws_manager
    async with _ws_manager_lock:
        if _ws_manager is None:
            _ws_manager = KISWebSocketManager()
        return _ws_manager


async def reset_websocket_manager() -> None:
    """테스트용: WebSocket 매니저 싱글톤 리셋."""
    global _ws_manager
    async with _ws_manager_lock:
        if _ws_manager is not None:
            await _ws_manager.stop()
            _ws_manager = None


class KISWebSocketManager:
    """WebSocket 연결 및 구독 관리 매니저.

    Agent가 USE_WEBSOCKET=true로 실행될 때 사용되는 매니저.
    백그라운드에서 WebSocket 연결을 유지하고 시세 데이터를 캐시에 자동 업데이트.

    특징:
    - 최대 40개 심볼 구독 (KIS 제한)
    - 백그라운드 asyncio Task로 실행
    - 캐시 자동 업데이트 (create_cache_updating_callback 활용)
    - 자동 재연결 지원
    """

    MAX_SYMBOLS = 40

    def __init__(self) -> None:
        """초기화."""
        self._client: Optional[KISWebSocketClient] = None
        self._task: Optional[asyncio.Task] = None
        self._subscribed_symbols: set[str] = set()
        self._running = False

    @property
    def is_running(self) -> bool:
        """WebSocket 실행 중 여부."""
        return self._running and self._client is not None and self._client.is_connected

    @property
    def subscribed_count(self) -> int:
        """현재 구독된 심볼 수."""
        return len(self._subscribed_symbols)

    def get_subscribed_symbols(self) -> list[str]:
        """구독 중인 심볼 목록 반환."""
        return list(self._subscribed_symbols)

    async def start(self, symbols: list[str], is_paper: bool = True) -> None:
        """WebSocket 연결 시작 및 심볼 구독.

        Args:
            symbols: 구독할 심볼 목록 (최대 40개까지만 구독)
            is_paper: 모의투자 여부 (기본값: True)
        """
        if self._running:
            logger.warning("WebSocket manager already running")
            return

        settings = load_kis_settings()

        # 캐시 업데이트 콜백이 포함된 클라이언트 생성
        self._client = KISWebSocketClient(
            settings=settings,
            is_paper=is_paper,
            on_tick=create_cache_updating_callback(),
        )

        # 연결
        await self._client.connect()
        self._running = True

        # 심볼 구독 (40개 제한)
        await self._subscribe_symbols(symbols[:self.MAX_SYMBOLS])

        # 백그라운드 수신 루프 시작
        self._task = asyncio.create_task(self._run_receive_loop())

        logger.info(
            "WebSocket manager started: %d/%d symbols subscribed",
            len(self._subscribed_symbols),
            len(symbols),
        )

    async def _subscribe_symbols(self, symbols: list[str]) -> None:
        """복수 심볼 구독.

        Args:
            symbols: 구독할 심볼 목록
        """
        for symbol in symbols:
            if len(self._subscribed_symbols) >= self.MAX_SYMBOLS:
                logger.warning(
                    "Max subscription limit reached (%d), skipping remaining symbols",
                    self.MAX_SYMBOLS,
                )
                break

            try:
                market = detect_market(symbol)
                await self._client.subscribe_quote(symbol, market)
                self._subscribed_symbols.add(symbol.upper())
                # 구독 요청 간 약간의 딜레이 (Rate limiting)
                await asyncio.sleep(0.1)
            except Exception as e:
                logger.error("Failed to subscribe %s: %s", symbol, e)

    async def _run_receive_loop(self) -> None:
        """백그라운드 수신 루프."""
        try:
            await self._client.run()
        except asyncio.CancelledError:
            logger.info("WebSocket receive loop cancelled")
        except Exception as e:
            logger.error("WebSocket receive loop error: %s", e)

    async def stop(self) -> None:
        """WebSocket 연결 종료 및 정리."""
        if not self._running:
            return

        self._running = False

        # 백그라운드 태스크 취소
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None

        # 클라이언트 연결 종료
        if self._client:
            await self._client.disconnect()
            self._client = None

        self._subscribed_symbols.clear()
        logger.info("WebSocket manager stopped")
