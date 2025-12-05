"""pytest 공통 설정 및 fixture.

이 파일은 모든 테스트에서 공유되는 설정과 fixture를 정의합니다.

E2E 테스트 실행:
    RUN_KIS_SMOKE=true pytest tests/test_kis_e2e.py -v

단위 테스트 실행:
    pytest tests/ -v -m "not kis_smoke"
"""

import os
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional
from unittest.mock import MagicMock

import pytest


# ============================================================================
# 상수 정의
# ============================================================================

# E2E 테스트 지연 시간 (Rate Limit 방지)
E2E_TEST_DELAY = 0.5

# 테스트용 심볼
TEST_SYMBOLS = ["AAPL", "MSFT", "GOOGL"]


# ============================================================================
# pytest 마커 등록
# ============================================================================

def pytest_configure(config):
    """pytest 마커를 등록합니다."""
    config.addinivalue_line(
        "markers", "kis_smoke: KIS API 스모크 테스트 (RUN_KIS_SMOKE=true 필요)"
    )
    config.addinivalue_line(
        "markers", "e2e: End-to-End 통합 테스트"
    )
    config.addinivalue_line(
        "markers", "slow: 느린 테스트 (Rate Limit 포함)"
    )


def pytest_collection_modifyitems(config, items):
    """kis_smoke 마커가 있는 테스트를 조건부로 스킵합니다."""
    if os.getenv("RUN_KIS_SMOKE") == "true":
        return
    skip_kis_smoke = pytest.mark.skip(reason="need RUN_KIS_SMOKE=true env var to run")
    for item in items:
        if "kis_smoke" in item.keywords:
            item.add_marker(skip_kis_smoke)


# ============================================================================
# 공통 Fixtures
# ============================================================================

@dataclass
class MockKISSettings:
    """Mock KISSettings 객체."""

    paper_app: str = "PSxxxxxxxx"
    paper_sec: str = "xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx"
    my_paper_stock: str = "50123456"
    my_prod: str = "01"
    my_agent: str = "Mozilla/5.0"
    my_app: Optional[str] = None
    my_sec: Optional[str] = None
    my_htsid: Optional[str] = None
    my_acct_stock: Optional[str] = None
    my_acct_future: Optional[str] = None
    my_paper_future: Optional[str] = None
    my_token: Optional[str] = None
    prod: str = "https://openapi.koreainvestment.com:9443"
    ops: str = "ws://ops.koreainvestment.com:21000"
    vps: str = "https://openapivts.koreainvestment.com:29443"
    vops: str = "ws://ops.koreainvestment.com:31000"


@pytest.fixture
def mock_kis_settings():
    """Mock KISSettings 객체를 생성합니다.

    Returns:
        MockKISSettings: 테스트용 KIS 설정 객체
    """
    return MockKISSettings()


@pytest.fixture
def mock_kis_client():
    """Mock KISRestClient를 생성합니다.

    Returns:
        MagicMock: 테스트용 KIS REST 클라이언트
    """
    return MagicMock()


@pytest.fixture
def mock_kis_authenticator():
    """Mock KISAuthenticator를 생성합니다.

    Returns:
        MagicMock: 테스트용 KIS 인증 객체
    """
    auth = MagicMock()
    auth.get_base_headers.return_value = {
        "authorization": "Bearer test_token",
        "appkey": "test_app_key",
        "appsecret": "test_secret",
    }

    # _ka 설정 (TREnv 모킹)
    tre = MagicMock()
    tre.my_url = "https://openapivts.koreainvestment.com:29443"
    tre.my_token = "test_token_12345"
    auth._ka = MagicMock()
    auth._ka.getTREnv.return_value = tre

    return auth


@pytest.fixture
def mock_kis_module():
    """Mock kis_auth 모듈을 생성합니다.

    Returns:
        MagicMock: 테스트용 kis_auth 모듈
    """
    module = MagicMock()

    # TREnv mock
    tre = MagicMock()
    tre.my_url = "https://openapivts.koreainvestment.com:29443"
    tre.my_token = "test_token_12345"
    module.getTREnv.return_value = tre

    # Base headers mock
    module._base_headers = {"authorization": "", "User-Agent": ""}
    module._getBaseHeader.return_value = {
        "authorization": "Bearer test_token_12345",
        "appkey": "test_app_key",
        "appsecret": "test_secret",
    }

    return module


# ============================================================================
# E2E 테스트용 Fixtures
# ============================================================================

@dataclass
class KISServiceContext:
    """KIS 서비스 컨텍스트 (E2E 테스트용)."""

    settings: Any
    auth: Any
    client: Any
    quote: Any
    account: Any
    order: Any
    test_delay: float = E2E_TEST_DELAY

    def wait(self, multiplier: float = 1.0) -> None:
        """Rate limit 방지를 위한 대기."""
        time.sleep(self.test_delay * multiplier)


@pytest.fixture(scope="module")
def kis_e2e_context():
    """E2E 테스트용 KIS 서비스 컨텍스트를 생성합니다.

    이 fixture는 모듈 단위로 공유되어 인증 오버헤드를 줄입니다.

    Returns:
        KISServiceContext: KIS 서비스 컨텍스트

    Raises:
        pytest.skip: KIS 설정 파일이 없는 경우
    """
    # E2E 테스트 환경 확인
    if os.getenv("RUN_KIS_SMOKE") != "true":
        pytest.skip("E2E 테스트는 RUN_KIS_SMOKE=true 환경변수가 필요합니다")

    from integrations.kis_settings import load_kis_settings
    from integrations.kis_auth_manager import KISAuthenticator
    from integrations.kis_client import KISRestClient
    from integrations.kis_quote import KISQuoteService
    from integrations.kis_account import KISAccountService
    from integrations.kis_order import KISOrderService

    try:
        settings = load_kis_settings()
    except FileNotFoundError as e:
        pytest.skip(f"KIS 설정 파일이 없습니다: {e}")

    auth = KISAuthenticator(settings, svr="vps")

    # 인증 수행 (TREnv.my_url 설정)
    auth.authenticate()
    time.sleep(E2E_TEST_DELAY)

    client = KISRestClient(auth)

    return KISServiceContext(
        settings=settings,
        auth=auth,
        client=client,
        quote=KISQuoteService(client, market="NAS"),
        account=KISAccountService(client, settings),
        order=KISOrderService(client, settings),
    )


@pytest.fixture
def e2e_delay():
    """E2E 테스트용 지연 시간을 반환합니다."""
    return E2E_TEST_DELAY


@pytest.fixture
def test_symbols():
    """테스트용 심볼 목록을 반환합니다."""
    return TEST_SYMBOLS.copy()
