"""해외주식 뉴스 조회 서비스.

KIS Open API [해외주식] 시세분석 > 해외뉴스종합(제목) [v1_해외주식-053]
TR ID: HHPSTH60100C1 (실전/모의투자 공통)

응답 필드 매핑:
  - info_gb: 뉴스구분
  - news_key: 뉴스키
  - data_dt: 조회일자
  - data_tm: 조회시간
  - class_cd: 중분류
  - class_name: 중분류명
  - source: 자료원
  - nation_cd: 국가코드
  - exchange_cd: 거래소코드
  - symb: 종목코드
  - symb_name: 종목명
  - title: 제목
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from integrations.kis_client import KISRestClient

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class NewsArticle:
    """뉴스 기사를 표현하는 모델."""

    title: str
    source: str
    date: str
    time: str
    symbol: Optional[str] = None
    symbol_name: Optional[str] = None
    category: Optional[str] = None
    news_key: Optional[str] = None
    raw: Dict[str, Any] = field(default_factory=dict)


class KISNewsService:
    """KIS 해외주식 뉴스 조회 래퍼.

    해외 주식 관련 뉴스를 조회합니다.

    Args:
        client: KIS REST API 클라이언트

    Example:
        >>> service = KISNewsService(client)
        >>> articles = service.get_overseas_news(nation_cd="US", symbol="AAPL")
        >>> for article in articles:
        ...     print(article.title)
    """

    API_PATH = "/uapi/overseas-price/v1/quotations/news-title"
    TR_ID = "HHPSTH60100C1"

    def __init__(self, client: KISRestClient) -> None:
        self._client = client

    def _build_params(
        self,
        nation_cd: str = "",
        symbol: str = "",
        date: str = "",
        time: str = "",
        cts: str = "",
    ) -> Dict[str, str]:
        """API 요청 파라미터를 구성합니다."""
        return {
            "INFO_GB": "",  # 뉴스구분 (빈 값: 전체)
            "CLASS_CD": "",  # 중분류 (빈 값: 전체)
            "NATION_CD": nation_cd,  # 국가코드 (US, CN, HK 등)
            "EXCHANGE_CD": "",  # 거래소코드 (빈 값: 전체)
            "SYMB": symbol.upper() if symbol else "",  # 종목코드
            "DATA_DT": date,  # 조회일자 (YYYYMMDD)
            "DATA_TM": time,  # 조회시간 (HHMMSS)
            "CTS": cts,  # 다음키 (페이지네이션)
        }

    def _parse_article(self, item: Dict[str, Any]) -> NewsArticle:
        """API 응답 항목을 NewsArticle로 변환합니다."""
        return NewsArticle(
            title=item.get("title", ""),
            source=item.get("source", ""),
            date=item.get("data_dt", ""),
            time=item.get("data_tm", ""),
            symbol=item.get("symb") or None,
            symbol_name=item.get("symb_name") or None,
            category=item.get("class_name") or None,
            news_key=item.get("news_key") or None,
            raw=item,
        )

    def get_overseas_news(
        self,
        nation_cd: str = "US",
        symbol: str = "",
        date: str = "",
        time: str = "",
        max_results: int = 20,
    ) -> List[NewsArticle]:
        """해외주식 뉴스를 조회합니다.

        Args:
            nation_cd: 국가코드 (US: 미국, CN: 중국, HK: 홍콩, 빈값: 전체)
            symbol: 종목코드 (예: "AAPL", 빈값: 전체)
            date: 조회일자 (YYYYMMDD 형식, 빈값: 최신)
            time: 조회시간 (HHMMSS 형식, 빈값: 전체)
            max_results: 최대 결과 개수

        Returns:
            List[NewsArticle]: 뉴스 기사 목록

        Raises:
            ValueError: API 호출 실패 시
        """
        params = self._build_params(
            nation_cd=nation_cd,
            symbol=symbol,
            date=date,
            time=time,
        )

        try:
            # paginate=False로 단일 페이지만 조회
            # 필요시 paginate=True로 변경하여 자동 페이징 가능
            payload = self._client.request(
                "GET",
                self.API_PATH,
                tr_id=self.TR_ID,
                params=params,
                paginate=False,
            )
        except Exception as exc:
            logger.error("KIS 뉴스 조회 실패: %s", exc)
            raise ValueError(f"KIS 뉴스 조회 실패: {exc}") from exc

        # 응답 파싱
        if not isinstance(payload, dict):
            logger.warning("KIS 뉴스 응답이 dict가 아님: %s", type(payload))
            return []

        # outblock1 필드에서 뉴스 목록 추출
        output = payload.get("outblock1") or payload.get("output") or []
        if not isinstance(output, list):
            output = [output] if output else []

        articles = []
        for item in output[:max_results]:
            try:
                article = self._parse_article(item)
                if article.title:  # 제목이 있는 기사만 포함
                    articles.append(article)
            except Exception as exc:
                logger.warning("뉴스 항목 파싱 실패: %s", exc)
                continue

        logger.debug(
            "KIS 뉴스 조회 완료: nation=%s, symbol=%s, count=%d",
            nation_cd, symbol, len(articles)
        )

        return articles


__all__ = ["KISNewsService", "NewsArticle"]
