"""실시간 시세 캐싱 모듈.

WebSocket으로 수신한 실시간 시세를 캐싱하고,
에이전트가 이를 활용할 수 있도록 제공한다.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from threading import Lock
from typing import Any, Callable, Dict, Optional

logger = logging.getLogger(__name__)


@dataclass
class CachedQuote:
    """캐시된 시세 데이터."""

    symbol: str
    price: float
    timestamp: datetime
    source: str = "websocket"  # "rest" or "websocket"
    volume: Optional[int] = None
    change: float = 0.0
    change_rate: float = 0.0
    open_price: float = 0.0
    high_price: float = 0.0
    low_price: float = 0.0


@dataclass
class CacheStats:
    """캐시 통계 데이터."""

    hits: int = 0
    misses: int = 0
    updates: int = 0
    evictions: int = 0
    websocket_updates: int = 0
    rest_updates: int = 0

    @property
    def hit_rate(self) -> float:
        """캐시 히트율 계산."""
        total = self.hits + self.misses
        return (self.hits / total * 100) if total > 0 else 0.0


class KISQuoteCache:
    """실시간 시세 캐시.

    Thread-safe한 시세 캐시 구현.
    TTL 기반으로 오래된 데이터를 자동 만료시킨다.

    Args:
        ttl_seconds: 캐시 TTL (기본값: 5초)
        max_size: 최대 캐시 크기 (기본값: 1000, 0이면 무제한)
    """

    def __init__(self, ttl_seconds: float = 5.0, max_size: int = 1000) -> None:
        self._cache: Dict[str, CachedQuote] = {}
        self._lock = Lock()
        self._ttl = timedelta(seconds=ttl_seconds)
        self._max_size = max_size
        self._stats = CacheStats()

    @property
    def ttl_seconds(self) -> float:
        """현재 TTL (초)."""
        return self._ttl.total_seconds()

    @ttl_seconds.setter
    def ttl_seconds(self, value: float) -> None:
        """TTL 설정."""
        self._ttl = timedelta(seconds=value)

    def update(
        self,
        symbol: str,
        price: float,
        source: str = "websocket",
        *,
        volume: Optional[int] = None,
        change: float = 0.0,
        change_rate: float = 0.0,
        open_price: float = 0.0,
        high_price: float = 0.0,
        low_price: float = 0.0,
    ) -> None:
        """시세 업데이트.

        Args:
            symbol: 종목 심볼
            price: 현재가
            source: 데이터 소스 ("websocket" or "rest")
            volume: 거래량
            change: 전일 대비
            change_rate: 등락률
            open_price: 시가
            high_price: 고가
            low_price: 저가
        """
        symbol_upper = symbol.upper()
        with self._lock:
            # 최대 크기 초과 시 가장 오래된 항목 제거
            if self._max_size > 0 and len(self._cache) >= self._max_size:
                if symbol_upper not in self._cache:
                    self._evict_oldest()

            self._cache[symbol_upper] = CachedQuote(
                symbol=symbol_upper,
                price=price,
                timestamp=datetime.now(),
                source=source,
                volume=volume,
                change=change,
                change_rate=change_rate,
                open_price=open_price,
                high_price=high_price,
                low_price=low_price,
            )
            self._stats.updates += 1

            if source == "websocket":
                self._stats.websocket_updates += 1
            else:
                self._stats.rest_updates += 1

            logger.debug("캐시 업데이트: %s = %.2f (source=%s)", symbol_upper, price, source)

    def _evict_oldest(self) -> None:
        """가장 오래된 캐시 항목 제거 (Lock 내에서 호출)."""
        if not self._cache:
            return

        oldest_symbol = min(self._cache.keys(), key=lambda s: self._cache[s].timestamp)
        del self._cache[oldest_symbol]
        self._stats.evictions += 1
        logger.debug("캐시 퇴거: %s", oldest_symbol)

    def get(self, symbol: str) -> Optional[CachedQuote]:
        """캐시된 시세 조회 (TTL 초과 시 None).

        Args:
            symbol: 종목 심볼

        Returns:
            캐시된 시세 또는 None (TTL 초과/미존재)
        """
        symbol_upper = symbol.upper()
        with self._lock:
            quote = self._cache.get(symbol_upper)
            if quote is None:
                self._stats.misses += 1
                return None

            # TTL 체크
            if datetime.now() - quote.timestamp > self._ttl:
                self._stats.misses += 1
                logger.debug("캐시 TTL 만료: %s", symbol_upper)
                return None

            self._stats.hits += 1
            return quote

    def get_or_fetch(
        self,
        symbol: str,
        fetch_fn: Callable[[str], float],
    ) -> float:
        """캐시 히트 시 캐시값, 미스 시 REST 조회.

        Args:
            symbol: 종목 심볼
            fetch_fn: REST API 조회 함수 (심볼 -> 가격)

        Returns:
            현재가
        """
        cached = self.get(symbol)
        if cached is not None:
            return cached.price

        # REST API로 조회
        price = fetch_fn(symbol)
        self.update(symbol, price, source="rest")
        return price

    def invalidate(self, symbol: str) -> bool:
        """특정 심볼의 캐시 무효화.

        Args:
            symbol: 종목 심볼

        Returns:
            무효화 성공 여부
        """
        symbol_upper = symbol.upper()
        with self._lock:
            if symbol_upper in self._cache:
                del self._cache[symbol_upper]
                return True
            return False

    def clear(self) -> int:
        """전체 캐시 삭제.

        Returns:
            삭제된 항목 수
        """
        with self._lock:
            count = len(self._cache)
            self._cache.clear()
            return count

    def get_stats(self) -> CacheStats:
        """캐시 통계 조회.

        Returns:
            캐시 통계 데이터
        """
        with self._lock:
            return CacheStats(
                hits=self._stats.hits,
                misses=self._stats.misses,
                updates=self._stats.updates,
                evictions=self._stats.evictions,
                websocket_updates=self._stats.websocket_updates,
                rest_updates=self._stats.rest_updates,
            )

    def reset_stats(self) -> None:
        """통계 초기화."""
        with self._lock:
            self._stats = CacheStats()

    def size(self) -> int:
        """현재 캐시된 항목 수.

        Returns:
            캐시 크기
        """
        with self._lock:
            return len(self._cache)

    def symbols(self) -> list[str]:
        """캐시된 모든 심볼 목록.

        Returns:
            심볼 리스트
        """
        with self._lock:
            return list(self._cache.keys())

    def get_all_valid(self) -> Dict[str, CachedQuote]:
        """TTL 유효한 모든 캐시 항목 조회.

        Returns:
            유효한 캐시 딕셔너리
        """
        now = datetime.now()
        with self._lock:
            return {
                symbol: quote
                for symbol, quote in self._cache.items()
                if now - quote.timestamp <= self._ttl
            }

    def __contains__(self, symbol: str) -> bool:
        """심볼이 캐시에 있는지 확인 (TTL 무시)."""
        return symbol.upper() in self._cache

    def __len__(self) -> int:
        """캐시 크기."""
        return self.size()

    def get_age(self, symbol: str) -> Optional[float]:
        """특정 심볼의 캐시 나이(초) 조회.

        Args:
            symbol: 종목 심볼

        Returns:
            캐시 나이(초) 또는 None (미존재)
        """
        symbol_upper = symbol.upper()
        with self._lock:
            quote = self._cache.get(symbol_upper)
            if quote is None:
                return None
            return (datetime.now() - quote.timestamp).total_seconds()

    def get_summary(self) -> str:
        """캐시 상태 요약 문자열 반환.

        Returns:
            사람이 읽기 좋은 상태 요약
        """
        stats = self.get_stats()
        valid_count = len(self.get_all_valid())
        total_count = self.size()

        return (
            f"Cache Summary: "
            f"{valid_count}/{total_count} valid entries, "
            f"TTL={self.ttl_seconds}s, "
            f"Hit rate={stats.hit_rate:.1f}% "
            f"({stats.hits} hits, {stats.misses} misses), "
            f"Updates: {stats.websocket_updates} WS + {stats.rest_updates} REST"
        )

    def get_health(self) -> Dict[str, Any]:
        """캐시 건강 상태 체크.

        Returns:
            건강 상태 딕셔너리:
            - healthy: 전체 건강 상태 (bool)
            - size: 현재 캐시 크기
            - valid_ratio: 유효한 항목 비율
            - hit_rate: 캐시 히트율
            - warnings: 경고 메시지 목록
        """
        stats = self.get_stats()
        total_count = self.size()
        valid_count = len(self.get_all_valid())
        valid_ratio = (valid_count / total_count * 100) if total_count > 0 else 100.0

        warnings: list[str] = []
        healthy = True

        # 경고 조건 체크
        if stats.hit_rate < 50 and (stats.hits + stats.misses) > 10:
            warnings.append(f"Low hit rate: {stats.hit_rate:.1f}%")
            healthy = False

        if self._max_size > 0 and total_count >= self._max_size * 0.9:
            warnings.append(f"Cache near capacity: {total_count}/{self._max_size}")

        if valid_ratio < 50 and total_count > 5:
            warnings.append(f"Many stale entries: {valid_ratio:.1f}% valid")

        if stats.evictions > stats.updates * 0.1 and stats.updates > 100:
            warnings.append(f"High eviction rate: {stats.evictions} evictions")

        return {
            "healthy": healthy,
            "size": total_count,
            "valid_count": valid_count,
            "valid_ratio": valid_ratio,
            "hit_rate": stats.hit_rate,
            "total_requests": stats.hits + stats.misses,
            "websocket_updates": stats.websocket_updates,
            "rest_updates": stats.rest_updates,
            "evictions": stats.evictions,
            "warnings": warnings,
        }


# =============================================================================
# Global Cache Instance
# =============================================================================

_quote_cache: Optional[KISQuoteCache] = None
_cache_lock = Lock()


def get_quote_cache(ttl_seconds: float = 5.0) -> KISQuoteCache:
    """전역 캐시 인스턴스 반환.

    Args:
        ttl_seconds: 캐시 TTL (초), 첫 생성 시에만 적용

    Returns:
        KISQuoteCache 인스턴스
    """
    global _quote_cache
    with _cache_lock:
        if _quote_cache is None:
            _quote_cache = KISQuoteCache(ttl_seconds=ttl_seconds)
            logger.info("전역 시세 캐시 초기화 (TTL=%.1fs)", ttl_seconds)
        return _quote_cache


def reset_quote_cache() -> None:
    """전역 캐시 초기화 (테스트용)."""
    global _quote_cache
    with _cache_lock:
        _quote_cache = None


__all__ = [
    "CachedQuote",
    "CacheStats",
    "KISQuoteCache",
    "get_quote_cache",
    "reset_quote_cache",
]
