"""KIS 체결 통보 핸들러 모듈.

WebSocket 체결 통보 수신 후 주문 로그 업데이트 및 에이전트 알림을 처리한다.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Protocol, TYPE_CHECKING

logger = logging.getLogger(__name__)


# =============================================================================
# Data Classes
# =============================================================================


@dataclass
class ExecutionRecord:
    """체결 기록 데이터."""

    order_no: str
    symbol: str
    side: str  # "buy" or "sell"
    executed_qty: int
    executed_price: float
    executed_at: str  # ISO format timestamp
    is_partial: bool = False
    remaining_qty: int = 0
    total_qty: int = 0
    account_no: str = ""
    original_order_no: str = ""

    def to_dict(self) -> Dict[str, Any]:
        """딕셔너리 변환."""
        return {
            "order_no": self.order_no,
            "symbol": self.symbol,
            "side": self.side,
            "executed_qty": self.executed_qty,
            "executed_price": self.executed_price,
            "executed_at": self.executed_at,
            "is_partial": self.is_partial,
            "remaining_qty": self.remaining_qty,
            "total_qty": self.total_qty,
            "account_no": self.account_no,
            "original_order_no": self.original_order_no,
        }


@dataclass
class OrderLogEntry:
    """주문 로그 엔트리."""

    timestamp: str
    date: str
    order_no: str
    symbol: str
    side: str
    qty: int
    limit_price: float
    message: str
    status: str  # submitted, filled, partial, cancelled
    broker: str
    source: str
    raw: Dict[str, Any] = field(default_factory=dict)
    executed_qty: int = 0
    executed_price: float = 0.0
    executions: List[Dict[str, Any]] = field(default_factory=list)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "OrderLogEntry":
        """딕셔너리에서 생성."""
        return cls(
            timestamp=data.get("timestamp", ""),
            date=data.get("date", ""),
            order_no=data.get("order_no", ""),
            symbol=data.get("symbol", ""),
            side=data.get("side", ""),
            qty=data.get("qty", 0),
            limit_price=data.get("limit_price", 0.0),
            message=data.get("message", ""),
            status=data.get("status", "submitted"),
            broker=data.get("broker", ""),
            source=data.get("source", ""),
            raw=data.get("raw", {}),
            executed_qty=data.get("executed_qty", 0),
            executed_price=data.get("executed_price", 0.0),
            executions=data.get("executions", []),
        )

    def to_dict(self) -> Dict[str, Any]:
        """딕셔너리 변환."""
        return {
            "timestamp": self.timestamp,
            "date": self.date,
            "order_no": self.order_no,
            "symbol": self.symbol,
            "side": self.side,
            "qty": self.qty,
            "limit_price": self.limit_price,
            "message": self.message,
            "status": self.status,
            "broker": self.broker,
            "source": self.source,
            "raw": self.raw,
            "executed_qty": self.executed_qty,
            "executed_price": self.executed_price,
            "executions": self.executions,
        }


# =============================================================================
# Callback Protocols
# =============================================================================


class OnExecutionRecordCallback(Protocol):
    """체결 기록 콜백."""

    def __call__(self, record: ExecutionRecord) -> None:
        ...


class OnOrderUpdateCallback(Protocol):
    """주문 상태 업데이트 콜백."""

    def __call__(self, entry: OrderLogEntry) -> None:
        ...


# =============================================================================
# Order Log Manager
# =============================================================================


class OrderLogManager:
    """kis_orders.jsonl 파일 관리자.

    주문 로그 파일을 읽고, 체결 통보에 따라 상태를 업데이트한다.
    """

    def __init__(self, log_file_path: Path) -> None:
        """초기화.

        Args:
            log_file_path: kis_orders.jsonl 파일 경로
        """
        self._log_file = log_file_path
        self._entries: Dict[str, OrderLogEntry] = {}
        self._load_entries()

    def _load_entries(self) -> None:
        """로그 파일에서 엔트리 로드."""
        if not self._log_file.exists():
            logger.info("주문 로그 파일이 없습니다: %s", self._log_file)
            return

        try:
            with open(self._log_file, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        data = json.loads(line)
                        entry = OrderLogEntry.from_dict(data)
                        self._entries[entry.order_no] = entry
                    except json.JSONDecodeError as e:
                        logger.warning("JSON 파싱 실패: %s - %s", line[:50], e)
        except Exception as e:
            logger.error("로그 파일 로드 실패: %s", e)

    def get_entry(self, order_no: str) -> Optional[OrderLogEntry]:
        """주문번호로 엔트리 조회."""
        return self._entries.get(order_no)

    def update_entry(self, order_no: str, execution: ExecutionRecord) -> Optional[OrderLogEntry]:
        """체결 정보로 엔트리 업데이트.

        Args:
            order_no: 주문번호
            execution: 체결 기록

        Returns:
            업데이트된 엔트리 또는 None
        """
        entry = self._entries.get(order_no)
        if entry is None:
            logger.warning("주문번호 %s를 찾을 수 없습니다.", order_no)
            return None

        # 체결 정보 추가
        entry.executions.append(execution.to_dict())
        entry.executed_qty += execution.executed_qty

        # 가중평균 체결가 계산
        total_value = sum(
            e.get("executed_qty", 0) * e.get("executed_price", 0)
            for e in entry.executions
        )
        if entry.executed_qty > 0:
            entry.executed_price = total_value / entry.executed_qty

        # 상태 업데이트
        if entry.executed_qty >= entry.qty:
            entry.status = "filled"
        elif entry.executed_qty > 0:
            entry.status = "partial"

        entry.message = f"체결: {entry.executed_qty}/{entry.qty} @ {entry.executed_price:.2f}"

        return entry

    def save_entries(self) -> None:
        """모든 엔트리를 파일에 저장 (전체 재작성)."""
        self._log_file.parent.mkdir(parents=True, exist_ok=True)

        with open(self._log_file, "w", encoding="utf-8") as f:
            for entry in self._entries.values():
                f.write(json.dumps(entry.to_dict(), ensure_ascii=False) + "\n")

        logger.info("주문 로그 저장 완료: %d건", len(self._entries))

    def append_execution_log(self, execution: ExecutionRecord) -> None:
        """체결 기록을 별도 로그에 추가 (선택적 사용)."""
        exec_log_file = self._log_file.parent / "kis_executions.jsonl"
        exec_log_file.parent.mkdir(parents=True, exist_ok=True)

        log_entry = {
            "timestamp": datetime.now().isoformat(),
            "type": "execution",
            **execution.to_dict(),
        }

        with open(exec_log_file, "a", encoding="utf-8") as f:
            f.write(json.dumps(log_entry, ensure_ascii=False) + "\n")


# =============================================================================
# Execution Handler
# =============================================================================


class KISExecutionHandler:
    """KIS 체결 통보 핸들러.

    WebSocket에서 수신한 체결 통보를 처리하고 주문 로그를 업데이트한다.
    """

    def __init__(
        self,
        log_dir: Optional[Path] = None,
        *,
        on_execution: Optional[OnExecutionRecordCallback] = None,
        on_order_update: Optional[OnOrderUpdateCallback] = None,
    ) -> None:
        """초기화.

        Args:
            log_dir: 로그 디렉토리 (None이면 기본 경로 사용)
            on_execution: 체결 통보 콜백
            on_order_update: 주문 상태 업데이트 콜백
        """
        self._log_dir = log_dir
        self._on_execution = on_execution
        self._on_order_update = on_order_update
        self._log_manager: Optional[OrderLogManager] = None
        self._callbacks: List[OnExecutionRecordCallback] = []

        if on_execution:
            self._callbacks.append(on_execution)

    def set_log_dir(self, log_dir: Path) -> None:
        """로그 디렉토리 설정.

        Args:
            log_dir: 로그 디렉토리 경로
        """
        self._log_dir = log_dir
        self._log_manager = None  # 다음 접근 시 재초기화

    def _get_log_manager(self) -> Optional[OrderLogManager]:
        """로그 매니저 인스턴스 반환."""
        if self._log_manager is not None:
            return self._log_manager

        if self._log_dir is None:
            logger.warning("로그 디렉토리가 설정되지 않았습니다.")
            return None

        log_file = self._log_dir / "kis_orders.jsonl"
        self._log_manager = OrderLogManager(log_file)
        return self._log_manager

    def add_callback(self, callback: OnExecutionRecordCallback) -> None:
        """체결 통보 콜백 추가."""
        self._callbacks.append(callback)

    def remove_callback(self, callback: OnExecutionRecordCallback) -> None:
        """체결 통보 콜백 제거."""
        if callback in self._callbacks:
            self._callbacks.remove(callback)

    def handle_execution_notice(self, data: Dict[str, Any]) -> Optional[ExecutionRecord]:
        """체결 통보 처리.

        WebSocket에서 수신한 raw 데이터를 ExecutionRecord로 변환하고,
        주문 로그를 업데이트한다.

        Args:
            data: WebSocket에서 수신한 체결 통보 데이터

        Returns:
            변환된 ExecutionRecord 또는 None
        """
        record = self._parse_execution_data(data)
        if record is None:
            return None

        # 주문 로그 업데이트
        log_manager = self._get_log_manager()
        if log_manager:
            updated_entry = log_manager.update_entry(record.order_no, record)
            if updated_entry:
                log_manager.save_entries()
                log_manager.append_execution_log(record)

                # 주문 업데이트 콜백 호출
                if self._on_order_update:
                    self._on_order_update(updated_entry)

        # 체결 콜백 호출
        for callback in self._callbacks:
            try:
                callback(record)
            except Exception as e:
                logger.error("체결 콜백 오류: %s", e)

        return record

    def _parse_execution_data(self, data: Dict[str, Any]) -> Optional[ExecutionRecord]:
        """체결 통보 데이터 파싱.

        Args:
            data: 체결 통보 데이터

        Returns:
            ExecutionRecord 또는 None
        """
        try:
            order_no = str(data.get("ODER_NO", "") or data.get("order_no", ""))
            if not order_no:
                logger.warning("주문번호가 없는 체결 통보: %s", data)
                return None

            # 매도매수 구분: 01=매도, 02=매수
            side_code = data.get("SELN_BYOV_CLS", "")
            side = "sell" if side_code == "01" else "buy"

            executed_qty = int(data.get("CNTG_QTY", 0) or data.get("executed_qty", 0))
            executed_price = float(data.get("CNTG_UNPR", 0) or data.get("executed_price", 0))
            total_qty = int(data.get("ODER_QTY", 0) or data.get("quantity", 0))

            # 체결 시간
            exec_time = data.get("STCK_CNTG_HOUR", "") or data.get("timestamp", "")
            if exec_time and len(exec_time) == 6:
                # HHMMSS 형식을 HH:MM:SS로 변환
                exec_time = f"{exec_time[:2]}:{exec_time[2:4]}:{exec_time[4:6]}"
            executed_at = exec_time or datetime.now().isoformat()

            remaining_qty = max(0, total_qty - executed_qty)
            is_partial = remaining_qty > 0

            return ExecutionRecord(
                order_no=order_no,
                symbol=str(data.get("STCK_SHRN_ISCD", "") or data.get("symbol", "")),
                side=side,
                executed_qty=executed_qty,
                executed_price=executed_price,
                executed_at=executed_at,
                is_partial=is_partial,
                remaining_qty=remaining_qty,
                total_qty=total_qty,
                account_no=str(data.get("ACNT_NO", "") or data.get("account_no", "")),
                original_order_no=str(data.get("OODER_NO", "") or data.get("original_order_no", "")),
            )

        except Exception as e:
            logger.error("체결 데이터 파싱 실패: %s - %s", data, e)
            return None

    def reload_log(self) -> None:
        """로그 파일 다시 로드."""
        self._log_manager = None
        self._get_log_manager()


# =============================================================================
# Helper Functions
# =============================================================================


def create_execution_handler_from_config() -> KISExecutionHandler:
    """설정에서 체결 핸들러 생성.

    Returns:
        설정 기반으로 초기화된 KISExecutionHandler
    """
    import os
    import sys

    project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    sys.path.insert(0, project_root)

    try:
        from tools.general_tools import get_config_value
    except ImportError:
        get_config_value = lambda k, d=None: os.getenv(k, d)

    log_path = get_config_value("LOG_PATH", "./data/agent_data")
    signature = get_config_value("SIGNATURE") or "unknown"

    if log_path.startswith("./data/"):
        log_rel = log_path[7:]
    else:
        log_rel = log_path

    base_dir = Path(project_root) / "data" / log_rel / signature / "position"

    return KISExecutionHandler(log_dir=base_dir)


# =============================================================================
# Agent Notification
# =============================================================================


class AgentNotifier:
    """에이전트에 체결 통보를 알리는 클래스.

    콘솔 출력, 로깅, 사용자 정의 콜백을 통해 체결 정보를 전달한다.
    """

    def __init__(
        self,
        *,
        enable_console: bool = True,
        enable_logging: bool = True,
        custom_callbacks: Optional[List[Callable[[ExecutionRecord], None]]] = None,
    ) -> None:
        """초기화.

        Args:
            enable_console: 콘솔 출력 활성화
            enable_logging: 로깅 활성화
            custom_callbacks: 사용자 정의 콜백 리스트
        """
        self._enable_console = enable_console
        self._enable_logging = enable_logging
        self._callbacks = custom_callbacks or []

    def add_callback(self, callback: Callable[[ExecutionRecord], None]) -> None:
        """콜백 추가."""
        self._callbacks.append(callback)

    def notify(self, record: ExecutionRecord) -> None:
        """체결 통보 알림.

        Args:
            record: 체결 기록
        """
        # 콘솔 출력
        if self._enable_console:
            self._print_notification(record)

        # 로깅
        if self._enable_logging:
            logger.info(
                "체결 알림: %s %s %d주 @ %.2f [%s]",
                record.symbol,
                record.side.upper(),
                record.executed_qty,
                record.executed_price,
                "부분체결" if record.is_partial else "완전체결",
            )

        # 사용자 콜백 호출
        for callback in self._callbacks:
            try:
                callback(record)
            except Exception as e:
                logger.error("알림 콜백 오류: %s", e)

    def _print_notification(self, record: ExecutionRecord) -> None:
        """콘솔에 체결 알림 출력."""
        status = "부분체결" if record.is_partial else "완전체결"
        side_emoji = "🟢" if record.side == "buy" else "🔴"
        side_text = "매수" if record.side == "buy" else "매도"

        print(
            f"\n{side_emoji} 체결 통보: {record.symbol} {side_text} "
            f"{record.executed_qty}주 @ ${record.executed_price:.2f} [{status}]"
        )
        if record.is_partial:
            print(f"   └─ 잔여 수량: {record.remaining_qty}주")


def create_agent_notifier(
    on_execution: Optional[Callable[[ExecutionRecord], None]] = None,
) -> AgentNotifier:
    """에이전트 알림 객체 생성.

    Args:
        on_execution: 체결 시 호출할 콜백

    Returns:
        설정된 AgentNotifier 인스턴스
    """
    notifier = AgentNotifier()
    if on_execution:
        notifier.add_callback(on_execution)
    return notifier


def notify_agent_execution(record: ExecutionRecord) -> None:
    """에이전트에 체결 통보 알림 (단순 함수 버전).

    Args:
        record: 체결 기록
    """
    notifier = AgentNotifier(enable_console=True, enable_logging=True)
    notifier.notify(record)


# =============================================================================
# Convenience Functions
# =============================================================================


def create_execution_handler_with_notifier(
    log_dir: Optional[Path] = None,
    *,
    on_agent_notify: Optional[Callable[[ExecutionRecord], None]] = None,
) -> KISExecutionHandler:
    """알림 기능이 포함된 체결 핸들러 생성.

    Args:
        log_dir: 로그 디렉토리
        on_agent_notify: 에이전트 알림 콜백

    Returns:
        설정된 KISExecutionHandler 인스턴스
    """
    notifier = create_agent_notifier(on_agent_notify)

    def on_execution(record: ExecutionRecord) -> None:
        notifier.notify(record)

    return KISExecutionHandler(log_dir=log_dir, on_execution=on_execution)


__all__ = [
    "ExecutionRecord",
    "OrderLogEntry",
    "OrderLogManager",
    "KISExecutionHandler",
    "OnExecutionRecordCallback",
    "OnOrderUpdateCallback",
    "create_execution_handler_from_config",
    "AgentNotifier",
    "create_agent_notifier",
    "notify_agent_execution",
    "create_execution_handler_with_notifier",
]
