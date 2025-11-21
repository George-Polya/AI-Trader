"""agent_tools 계층에서 KIS 설정을 지연 로드/캐시하는 헬퍼."""

from __future__ import annotations

from typing import Optional

from integrations.kis_settings import (
    KISSettings,
    is_kis_broker,
    load_kis_settings,
)

_settings_cache: Optional[KISSettings] = None


def ensure_kis_settings(path: str | None = None) -> KISSettings:
    """BROKER가 kis일 때 KIS 설정을 한 번만 로드해 재사용한다."""
    global _settings_cache

    if not is_kis_broker():
        raise RuntimeError("BROKER가 kis가 아니어서 KIS 설정을 로드하지 않습니다.")

    if _settings_cache is not None and path is None:
        return _settings_cache

    try:
        settings = load_kis_settings(path)
    except Exception as exc:
        raise RuntimeError(f"KIS 설정 로드에 실패했습니다: {exc}") from exc

    _settings_cache = settings
    return settings
