"""KIS 인증 흐름을 래핑해 토큰 관리와 헤더 생성을 담당한다."""

from __future__ import annotations

import importlib.util
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Optional

from integrations.kis_settings import KISSettings

PROJECT_ROOT = Path(__file__).resolve().parents[1]
KIS_AUTH_PATH = PROJECT_ROOT / "open-trading-api" / "examples_user" / "kis_auth.py"


def _load_kis_auth_module():
    """동적 로딩으로 kis_auth 모듈을 불러온다."""
    spec = importlib.util.spec_from_file_location("kis_auth", KIS_AUTH_PATH)
    if spec is None or spec.loader is None:
        raise ImportError(f"kis_auth 모듈을 로드할 수 없습니다: {KIS_AUTH_PATH}")
    module = importlib.util.module_from_spec(spec)
    loader = spec.loader
    assert loader is not None
    loader.exec_module(module)
    return module


def _to_ka_cfg(settings: KISSettings) -> dict[str, Any]:
    """kis_auth 모듈에서 기대하는 설정 키로 매핑."""
    return {
        "paper_app": settings.paper_app,
        "paper_sec": settings.paper_sec,
        "my_paper_stock": settings.my_paper_stock,
        "my_prod": settings.my_prod,
        "my_agent": settings.my_agent,
        "my_app": settings.my_app,
        "my_sec": settings.my_sec,
        "my_htsid": settings.my_htsid,
        "my_acct_stock": settings.my_acct_stock,
        "my_acct_future": settings.my_acct_future,
        "my_paper_future": settings.my_paper_future,
        "my_token": settings.my_token,
        "prod": settings.prod,
        "ops": settings.ops,
        "vps": settings.vps,
        "vops": settings.vops,
    }


class KISAuthenticator:
    """kis_auth.py를 감싸 토큰 재사용/재발급과 헤더 생성을 관리한다."""

    def __init__(
        self,
        settings: KISSettings,
        *,
        svr: str = "vps",
        product: str = "01",
        refresh_margin_seconds: int = 300,
        kis_module: Optional[Any] = None,
    ) -> None:
        self.settings = settings
        self.svr = svr
        self.product = product
        self.refresh_margin = timedelta(seconds=refresh_margin_seconds)
        self._ka = kis_module or _load_kis_auth_module()
        self._token: Optional[str] = None
        self._expires_at: Optional[datetime] = None
        self._prime_module_config()

    def _prime_module_config(self) -> None:
        """kis_auth 모듈의 전역 설정을 KISSettings 기반으로 갱신."""
        cfg = _to_ka_cfg(self.settings)
        setattr(self._ka, "_cfg", cfg)
        base_headers = getattr(self._ka, "_base_headers", None)
        if isinstance(base_headers, dict):
            base_headers["User-Agent"] = self.settings.my_agent
        # 동작 중 재로딩을 대비해 sys.path에 프로젝트 루트를 추가
        root_str = str(PROJECT_ROOT)
        if root_str not in sys.path:
            sys.path.insert(0, root_str)

    def _extract_token(self) -> Optional[str]:
        """auth 호출 후 토큰을 추출."""
        tre = self._ka.getTREnv()
        token = getattr(tre, "my_token", None)
        if token:
            return token
        base_headers = getattr(self._ka, "_base_headers", {})
        auth_header = base_headers.get("authorization")
        if isinstance(auth_header, str) and auth_header.startswith("Bearer "):
            return auth_header.replace("Bearer ", "", 1).strip()
        return None

    def authenticate(self, force: bool = False) -> str:
        """남은 유효시간이 마진보다 길면 재사용, 아니면 재인증."""
        now = datetime.now(timezone.utc)
        if (
            not force
            and self._token
            and self._expires_at
            and now + self.refresh_margin < self._expires_at
        ):
            return self._token

        self._prime_module_config()
        try:
            self._ka.auth(svr=self.svr, product=self.product)
        except Exception as exc:
            raise RuntimeError(f"KIS 인증에 실패했습니다: {exc}") from exc

        token = self._extract_token()
        if not token:
            raise RuntimeError("KIS 인증 후 토큰을 가져오지 못했습니다.")

        self._token = token
        # KIS 토큰 유효시간은 1일이므로 여유 있게 23시간으로 설정
        self._expires_at = now + timedelta(hours=23)
        return token

    def refresh(self) -> str:
        """강제 재인증."""
        return self.authenticate(force=True)

    def get_base_headers(self, body: Optional[dict[str, Any]] = None, include_hash: bool = False) -> dict[str, Any]:
        """인증을 보장한 뒤 공통 헤더를 반환. 필요한 경우 hashkey를 포함."""
        self.authenticate()
        try:
            headers = self._ka._getBaseHeader()
        except Exception as exc:
            raise RuntimeError(f"기본 헤더 생성에 실패했습니다: {exc}") from exc

        if include_hash:
            if body is None:
                raise ValueError("include_hash=True인 경우 body가 필요합니다.")
            try:
                self._ka.set_order_hash_key(headers, body)
            except Exception as exc:
                raise RuntimeError(f"hashkey 생성에 실패했습니다: {exc}") from exc
        return headers

    @property
    def token(self) -> Optional[str]:
        return self._token

    @property
    def expires_at(self) -> Optional[datetime]:
        return self._expires_at


__all__ = ["KISAuthenticator"]
