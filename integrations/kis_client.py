"""KIS REST 클라이언트: 인증 헤더 구성, TR_CONT 페이징, 429 재시도를 담당한다."""

from __future__ import annotations

import time
from typing import Any, Dict, List, Optional

import requests

from integrations.kis_auth_manager import KISAuthenticator


class KISAPIError(RuntimeError):
    """KIS API 오류를 표현하는 예외."""

    def __init__(self, code: str, message: str, status_code: int | None = None) -> None:
        super().__init__(f"[{status_code}] {code}: {message}")
        self.code = code
        self.message = message
        self.status_code = status_code


class KISRestClient:
    """공통 HTTP 호출 래퍼."""

    def __init__(
        self,
        authenticator: KISAuthenticator,
        *,
        session: Optional[requests.Session] = None,
        max_retries: int = 3,
    ) -> None:
        self.authenticator = authenticator
        self.session = session or requests.Session()
        self.max_retries = max_retries
        self._ka = authenticator._ka  # pragma: allowlist secret

    def _base_url(self) -> str:
        tre = self._ka.getTREnv()
        url = getattr(tre, "my_url", None)
        if not url:
            raise RuntimeError("KIS TREnv에서 my_url을 찾을 수 없습니다.")
        return url.rstrip("/")

    def _smart_sleep(self) -> None:
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
        """KIS REST 호출을 수행하고, tr_cont 페이징/429 재시도를 처리한다."""
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
            retries = 0
            while True:
                response = self.session.request(
                    method=method,
                    url=url,
                    params=params or None,
                    json=json,
                    data=data if json is None else None,
                    headers=headers,
                )
                if response.status_code == 429 and retries < self.max_retries:
                    retries += 1
                    self._smart_sleep()
                    continue
                break

            if response.status_code >= 400:
                raise KISAPIError("http_error", response.text, response.status_code)

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

            results.append(payload)

            if not paginate:
                break

            tr_cont = response.headers.get("tr_cont")
            if not tr_cont or tr_cont.upper() != "M":
                break

            fk = response.headers.get("ctx_area_fk100")
            br = response.headers.get("ctx_area_br100")
            if fk:
                params["CTX_AREA_FK100"] = fk
            if br:
                params["CTX_AREA_BR100"] = br

        if len(results) == 1:
            return results[0]
        return results


__all__ = ["KISRestClient", "KISAPIError"]
