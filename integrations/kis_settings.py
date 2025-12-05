"""KIS 설정 로더와 브로커 모드 토글 헬퍼."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Optional

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from tools.general_tools import get_config_value

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_KIS_CONFIG_PATH = PROJECT_ROOT / "open-trading-api" / "kis_devlp.yaml"
_BROKER_ENV_KEY = "BROKER"
_DEFAULT_BROKER = "local"
_WEBSOCKET_ENV_KEY = "USE_WEBSOCKET"
_SENSITIVE_KEYS = {"paper_app", "paper_sec", "my_app", "my_sec", "my_token"}


def _normalize_path(path: Path) -> Path:
    """프로젝트 루트 기준으로 상대경로를 절대경로로 변환."""
    if path.is_absolute():
        return path
    return (PROJECT_ROOT / path).resolve()


def _mask_secret(value: Optional[str]) -> str:
    """민감 필드를 repr에서 숨김."""
    if value is None:
        return "***"
    if len(value) <= 6:
        return "*" * len(value)
    return f"{value[:3]}...{value[-2:]}"


class KISSettings(BaseModel):
    """kis_devlp.yaml의 스키마."""

    paper_app: str = Field(..., description="모의투자 앱키")
    paper_sec: str = Field(..., description="모의투자 앱시크릿")
    my_paper_stock: str = Field(..., description="모의투자 증권계좌 8자리")
    my_prod: str = Field(..., description="계좌 상품코드 2자리")
    my_agent: str = Field(..., description="요청 헤더 User-Agent")
    my_app: Optional[str] = Field(default=None, description="실전투자 앱키")
    my_sec: Optional[str] = Field(default=None, description="실전투자 앱시크릿")
    my_htsid: Optional[str] = Field(default=None, description="HTS ID")
    my_acct_stock: Optional[str] = Field(default=None, description="실전투자 증권계좌 8자리")
    my_acct_future: Optional[str] = Field(default=None, description="실전투자 선물옵션계좌 8자리")
    my_paper_future: Optional[str] = Field(default=None, description="모의투자 선물옵션계좌 8자리")
    my_token: Optional[str] = Field(default=None, description="인증 토큰 캐시")
    prod: str = Field(default="https://openapi.koreainvestment.com:9443", description="실전 REST 엔드포인트")
    ops: str = Field(default="ws://ops.koreainvestment.com:21000", description="실전 WebSocket 엔드포인트")
    vps: str = Field(default="https://openapivts.koreainvestment.com:29443", description="모의투자 REST 엔드포인트")
    vops: str = Field(default="ws://ops.koreainvestment.com:31000", description="모의투자 WebSocket 엔드포인트")

    model_config = ConfigDict(extra="ignore")

    def masked_dump(self) -> dict[str, Any]:
        """민감정보를 마스킹한 dict 반환."""
        data = self.model_dump()
        for key in _SENSITIVE_KEYS:
            if key in data:
                data[key] = _mask_secret(data[key])
        return data

    def __repr__(self) -> str:
        masked = ", ".join(f"{k}={v}" for k, v in self.masked_dump().items())
        return f"KISSettings({masked})"


def _resolve_config_path(path: str | Path | None) -> Path:
    """우선순위: 명시적 인자 > env(KIS_CONFIG_PATH) > 기본값."""
    env_path = get_config_value("KIS_CONFIG_PATH")
    candidate = Path(path or env_path or DEFAULT_KIS_CONFIG_PATH)
    return _normalize_path(candidate)


def load_kis_settings(path: str | Path | None = None) -> KISSettings:
    """YAML 설정을 로드하고 스키마 검증."""
    config_path = _resolve_config_path(path)

    if not config_path.exists():
        raise FileNotFoundError(f"KIS 설정 파일이 없습니다: {config_path}")
    if not config_path.is_file():
        raise FileNotFoundError(f"KIS 설정 파일이 존재하지만 파일이 아닙니다: {config_path}")

    try:
        contents = config_path.read_text(encoding="utf-8")
    except PermissionError as exc:
        raise PermissionError(f"KIS 설정 파일을 읽을 수 없습니다: {config_path}") from exc

    try:
        data = yaml.safe_load(contents) or {}
    except yaml.YAMLError as exc:
        raise ValueError(f"KIS 설정 파일 파싱 실패: {config_path}") from exc

    if not isinstance(data, dict):
        raise ValueError(f"KIS 설정이 dict가 아닙니다: {config_path}")

    try:
        return KISSettings(**data)
    except ValidationError:
        # ValidationError 자체를 그대로 올려 호출자가 원인 필드를 확인할 수 있게 한다.
        raise


def get_broker_mode(default: str = _DEFAULT_BROKER) -> str:
    """BROKER 환경변수를 중앙에서 조회."""
    raw = get_config_value(_BROKER_ENV_KEY, default)
    normalized = (raw or default).strip().lower()
    return normalized or _DEFAULT_BROKER


def is_kis_broker() -> bool:
    """현재 브로커 모드가 kis인지 여부."""
    return get_broker_mode() == "kis"


def is_websocket_enabled() -> bool:
    """WebSocket 실시간 시세 활성화 여부.

    BROKER=kis이고 USE_WEBSOCKET=true인 경우에만 True 반환.
    WebSocket은 KIS 브로커 모드에서만 사용 가능.

    Returns:
        bool: WebSocket 활성화 여부
    """
    if not is_kis_broker():
        return False
    raw = get_config_value(_WEBSOCKET_ENV_KEY, "false")
    return str(raw).strip().lower() in ("true", "1", "yes")
