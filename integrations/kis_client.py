"""KIS REST 클라이언트: 인증 헤더 구성, TR_CONT 페이징, 429 재시도를 담당한다."""

from __future__ import annotations

import logging
import time
from typing import Any, ClassVar, Dict, FrozenSet, List, Optional

import requests

from integrations.kis_auth_manager import KISAuthenticator
from integrations.kis_rate_limiter import RateLimiter

logger = logging.getLogger(__name__)


class KISAPIError(RuntimeError):
    """KIS API 오류를 표현하는 예외.

    Attributes:
        code: KIS API 오류 코드 (예: "EGW00123", "http_error").
        message: 오류 메시지.
        status_code: HTTP 상태 코드.
        is_retryable: 재시도 가능 여부.
    """

    # 재시도 가능한 오류 코드 (Rate Limit, 일시적 서버 오류 등)
    # 주의: "http_error"는 HTTP 상태 코드로 판단하므로 여기에 포함하지 않음
    RETRYABLE_CODES: ClassVar[FrozenSet[str]] = frozenset({
        "EGW00123",        # Rate limit 초과
        "EGW00201",        # 일시적 시스템 오류
        "IGW00002",        # 서버 접속 지연
        "network_error",   # 네트워크 연결 오류
    })

    # 재시도 가능한 HTTP 상태 코드
    RETRYABLE_STATUS_CODES: ClassVar[FrozenSet[int]] = frozenset({
        429,  # Too Many Requests
        500,  # Internal Server Error
        502,  # Bad Gateway
        503,  # Service Unavailable
        504,  # Gateway Timeout
    })

    def __init__(self, code: str, message: str, status_code: int | None = None) -> None:
        super().__init__(f"[{status_code}] {code}: {message}")
        self.code = code
        self.message = message
        self.status_code = status_code

    @property
    def is_retryable(self) -> bool:
        """이 오류가 재시도 가능한지 판단한다.

        Returns:
            재시도 가능 여부. Rate limit 오류나 일시적 서버 오류인 경우 True.
        """
        if self.code in self.RETRYABLE_CODES:
            return True
        if self.status_code is not None and self.status_code in self.RETRYABLE_STATUS_CODES:
            return True
        return False

    @property
    def is_rate_limited(self) -> bool:
        """Rate limit 오류인지 판단한다."""
        return self.status_code == 429 or self.code == "EGW00123"


class KISRestClient:
    """공통 HTTP 호출 래퍼.

    KIS REST API 호출을 담당하며, 다음 기능을 제공한다:
    - Rate Limiting: 초당 20회 호출 제한 준수
    - 자동 재시도: 일시적 오류 시 지수 백오프로 재시도
    - TR_CONT 페이징: 대량 데이터 자동 페이징 처리
    - 인증 헤더: 토큰 및 해시키 자동 구성

    Attributes:
        authenticator: KIS 인증 관리자.
        session: HTTP 세션.
        max_retries: 최대 재시도 횟수.
        rate_limiter: API 호출 속도 제한기.
    """

    # 모의투자(VPS)는 초당 5회 제한이 더 안정적
    DEFAULT_CALLS_PER_SECOND: int = 5

    def __init__(
        self,
        authenticator: KISAuthenticator,
        *,
        session: Optional[requests.Session] = None,
        max_retries: int = 3,
        calls_per_second: int = DEFAULT_CALLS_PER_SECOND,
    ) -> None:
        """KISRestClient를 초기화한다.

        Args:
            authenticator: KIS 인증 관리자.
            session: HTTP 세션 (선택). 기본값은 새 Session.
            max_retries: 최대 재시도 횟수. 기본값 3.
            calls_per_second: 초당 API 호출 제한. 기본값 20.
        """
        self.authenticator = authenticator
        self.session = session or requests.Session()
        self.max_retries = max_retries
        self._ka = authenticator._ka  # pragma: allowlist secret
        self._rate_limiter = RateLimiter(calls_per_second=calls_per_second)

    @property
    def rate_limiter(self) -> RateLimiter:
        """Rate Limiter 인스턴스를 반환한다."""
        return self._rate_limiter

    def _base_url(self) -> str:
        tre = self._ka.getTREnv()
        url = getattr(tre, "my_url", None)
        if not url:
            raise RuntimeError("KIS TREnv에서 my_url을 찾을 수 없습니다.")
        return url.rstrip("/")

    def _get_retry_delay(self, attempt: int) -> float:
        """재시도 대기 시간을 계산한다 (지수 백오프).

        Args:
            attempt: 현재 시도 횟수 (0부터 시작).

        Returns:
            대기 시간(초). 지수 백오프로 0.5초, 1초, 2초, ... 증가.
        """
        base_delay = 0.5
        return min(base_delay * (2 ** attempt), 10.0)  # 최대 10초

    def _smart_sleep(self, seconds: float | None = None) -> None:
        """지정된 시간 또는 기본 딜레이로 대기한다.

        Args:
            seconds: 대기 시간(초). None이면 기본 smart_sleep 또는 0.5초.
        """
        if seconds is not None:
            time.sleep(seconds)
            return

        fn = getattr(self._ka, "smart_sleep", None)
        if callable(fn):
            fn()
        else:
            time.sleep(0.5)

    def _build_url(self, path: str) -> str:
        if path.startswith("http://") or path.startswith("https://"):
            return path
        return f"{self._base_url()}/{path.lstrip('/')}"

    def request(
        self,
        method: str,
        path: str,
        *,
        tr_id: str,
        params: Optional[Dict[str, Any]] = None,
        data: Optional[Dict[str, Any]] = None,
        json: Optional[Dict[str, Any]] = None,
        paginate: bool = True,
    ) -> Any:
        """KIS REST 호출을 수행한다.

        Rate limit을 준수하며, tr_cont 페이징과 오류 재시도를 처리한다.

        Args:
            method: HTTP 메소드 (GET, POST 등).
            path: API 경로.
            tr_id: 거래 ID.
            params: 쿼리 파라미터.
            data: form 데이터.
            json: JSON 바디.
            paginate: TR_CONT 페이징 처리 여부.

        Returns:
            API 응답 JSON (단일 또는 리스트).

        Raises:
            KISAPIError: API 오류 시.
            RuntimeError: JSON 파싱 실패 시.
        """
        # 인증을 먼저 수행하여 _TRENV (특히 my_url)가 설정되도록 함
        self.authenticator.authenticate()

        url = self._build_url(path)
        results: List[Dict[str, Any]] = []
        params = dict(params or {})
        body_for_hash = json if json is not None else data

        headers = self.authenticator.get_base_headers(
            body=body_for_hash,
            include_hash=method.upper() in {"POST", "PUT", "PATCH"},
        )
        headers["tr_id"] = tr_id
        headers.setdefault("custtype", "P")

        while True:
            response = self._execute_with_retry(method, url, params, json, data, headers)
            payload = self._parse_response(response)
            results.append(payload)

            if not paginate:
                break

            tr_cont = response.headers.get("tr_cont")
            if not tr_cont or tr_cont.upper() != "M":
                break

            # 페이징 컨텍스트 업데이트
            fk = response.headers.get("ctx_area_fk100")
            nk = response.headers.get("ctx_area_nk100")
            br = response.headers.get("ctx_area_br100")
            if fk:
                params["CTX_AREA_FK100"] = fk
            if nk:
                params["CTX_AREA_NK100"] = nk
            if br:
                params["CTX_AREA_BR100"] = br

        if len(results) == 1:
            return results[0]
        return results

    def _execute_with_retry(
        self,
        method: str,
        url: str,
        params: Dict[str, Any],
        json_body: Optional[Dict[str, Any]],
        data: Optional[Dict[str, Any]],
        headers: Dict[str, str],
    ) -> requests.Response:
        """Rate limit을 준수하며 요청을 실행하고, 오류 시 재시도한다.

        Args:
            method: HTTP 메소드.
            url: 요청 URL.
            params: 쿼리 파라미터.
            json_body: JSON 바디.
            data: form 데이터.
            headers: HTTP 헤더.

        Returns:
            성공한 HTTP 응답.

        Raises:
            KISAPIError: 최대 재시도 후에도 실패 시.
        """
        last_error: Optional[KISAPIError] = None

        for attempt in range(self.max_retries + 1):
            # Rate limit 확인
            waited = self._rate_limiter.acquire()
            if waited > 0:
                logger.debug("Rate limit 대기: %.2f초", waited)

            try:
                response = self.session.request(
                    method=method,
                    url=url,
                    params=params or None,
                    json=json_body,
                    data=data if json_body is None else None,
                    headers=headers,
                )

                # HTTP 오류 확인
                if response.status_code >= 400:
                    error = KISAPIError("http_error", response.text, response.status_code)
                    if error.is_retryable and attempt < self.max_retries:
                        last_error = error
                        delay = self._get_retry_delay(attempt)
                        logger.debug(
                            "재시도 가능한 HTTP 오류 (시도 %d/%d): %s. %.1f초 후 재시도.",
                            attempt + 1, self.max_retries + 1, error, delay
                        )
                        self._smart_sleep(delay)
                        continue
                    raise error

                return response

            except requests.RequestException as exc:
                # 네트워크 오류도 재시도
                if attempt < self.max_retries:
                    delay = self._get_retry_delay(attempt)
                    logger.debug(
                        "네트워크 오류 (시도 %d/%d): %s. %.1f초 후 재시도.",
                        attempt + 1, self.max_retries + 1, exc, delay
                    )
                    self._smart_sleep(delay)
                    continue
                raise KISAPIError("network_error", str(exc), None) from exc

        # 모든 재시도 실패
        if last_error:
            raise last_error
        raise KISAPIError("unknown_error", "최대 재시도 횟수 초과", None)

    def _parse_response(self, response: requests.Response) -> Dict[str, Any]:
        """응답을 파싱하고 비즈니스 로직 오류를 확인한다.

        Args:
            response: HTTP 응답.

        Returns:
            파싱된 JSON 페이로드.

        Raises:
            KISAPIError: API 비즈니스 로직 오류 시.
            RuntimeError: JSON 파싱 실패 시.
        """
        try:
            payload = response.json()
        except Exception as exc:
            raise RuntimeError(f"KIS 응답을 JSON으로 파싱하지 못했습니다: {exc}") from exc

        if payload.get("rt_cd") != "0":
            raise KISAPIError(
                code=str(payload.get("msg_cd", "")),
                message=str(payload.get("msg1", "")),
                status_code=response.status_code,
            )

        return payload


__all__ = ["KISRestClient", "KISAPIError"]
