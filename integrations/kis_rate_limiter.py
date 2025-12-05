"""KIS API Rate Limiter: 초당 호출 횟수를 제한한다."""

from __future__ import annotations

import time
from collections import deque
from threading import Lock
from typing import Deque


class RateLimiter:
    """초당 API 호출 횟수를 제한하는 클래스.

    KIS API는 초당 20회로 호출 횟수가 제한되어 있다.
    이 클래스는 호출 전에 rate limit을 확인하고,
    제한 초과 시 자동으로 대기한다.

    Thread-safe 구현으로 멀티스레드 환경에서도 안전하게 사용 가능하다.

    Example:
        >>> limiter = RateLimiter(calls_per_second=20)
        >>> for _ in range(25):
        ...     limiter.acquire()  # 20회 이후 자동 대기
        ...     # API 호출 수행
    """

    def __init__(self, calls_per_second: int = 20, *, window_seconds: float = 1.0) -> None:
        """RateLimiter를 초기화한다.

        Args:
            calls_per_second: 초당 허용 호출 횟수. 기본값 20 (KIS API 제한).
            window_seconds: 시간 윈도우 크기(초). 기본값 1.0.
        """
        if calls_per_second <= 0:
            raise ValueError("calls_per_second는 양수여야 합니다.")
        if window_seconds <= 0:
            raise ValueError("window_seconds는 양수여야 합니다.")

        self.calls_per_second = calls_per_second
        self.window_seconds = window_seconds
        self._timestamps: Deque[float] = deque(maxlen=calls_per_second)
        self._lock = Lock()

    def acquire(self) -> float:
        """호출 전 rate limit을 확인하고, 필요 시 대기한다.

        Returns:
            실제 대기한 시간(초). 대기하지 않았으면 0.0.
        """
        with self._lock:
            now = time.time()
            waited = 0.0

            # 시간 윈도우를 벗어난 오래된 타임스탬프 제거
            while self._timestamps and (now - self._timestamps[0]) > self.window_seconds:
                self._timestamps.popleft()

            # 제한 초과 시 대기
            if len(self._timestamps) >= self.calls_per_second:
                oldest = self._timestamps[0]
                sleep_time = self.window_seconds - (now - oldest) + 0.01  # 약간의 여유
                if sleep_time > 0:
                    time.sleep(sleep_time)
                    waited = sleep_time
                    now = time.time()
                    # 대기 후 다시 오래된 타임스탬프 정리
                    while self._timestamps and (now - self._timestamps[0]) > self.window_seconds:
                        self._timestamps.popleft()

            self._timestamps.append(now)
            return waited

    def reset(self) -> None:
        """호출 기록을 초기화한다."""
        with self._lock:
            self._timestamps.clear()

    @property
    def current_count(self) -> int:
        """현재 시간 윈도우 내의 호출 횟수를 반환한다."""
        with self._lock:
            now = time.time()
            # 시간 윈도우를 벗어난 타임스탬프 제거 후 카운트
            while self._timestamps and (now - self._timestamps[0]) > self.window_seconds:
                self._timestamps.popleft()
            return len(self._timestamps)

    @property
    def available_calls(self) -> int:
        """현재 즉시 사용 가능한 호출 횟수를 반환한다."""
        return max(0, self.calls_per_second - self.current_count)

    def __repr__(self) -> str:
        return (
            f"RateLimiter(calls_per_second={self.calls_per_second}, "
            f"window_seconds={self.window_seconds}, "
            f"current_count={self.current_count})"
        )


__all__ = ["RateLimiter"]
