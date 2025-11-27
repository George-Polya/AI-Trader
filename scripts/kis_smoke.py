#!/usr/bin/env python3
"""
KIS 스모크 테스트 스크립트
시세 -> 주문 -> 잔고/체결 흐름을 검증한다.
"""
import argparse
import sys
from pathlib import Path
from typing import Optional

# Add project root to sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from integrations.kis_settings import load_kis_settings, is_kis_broker
from integrations.kis_auth_manager import KISAuthenticator
from integrations.kis_client import KISRestClient
from integrations.kis_quote import KISQuoteService
from integrations.kis_order import KISOrderService
from integrations.kis_account import KISAccountService


def run_flow(symbol: str, qty: int, limit_price: Optional[float] = None) -> None:
    """
    시세 -> 주문 -> 잔고 전체 흐름 실행
    """
    # 1. 설정 및 클라이언트 초기화 (단일 인스턴스 공유)
    try:
        settings = load_kis_settings()
    except Exception as e:
        print(f"ERROR: KIS 설정 로드 실패: {e}")
        sys.exit(1)
        
    if not is_kis_broker():
        print("ERROR: BROKER 환경변수가 'kis'가 아닙니다. (BROKER=kis 설정 필요)")
        sys.exit(1)

    # 인증 및 클라이언트
    # svr="vps", product="01" -> 모의투자 설정
    auth = KISAuthenticator(settings, svr="vps", product="01")
    client = KISRestClient(auth)
    
    # 서비스 초기화
    quote_service = KISQuoteService(client)
    order_service = KISOrderService(client, settings)
    account_service = KISAccountService(client, settings)
    
    print(f"--- [1/3] 시세 조회: {symbol} ---")
    try:
        quote = quote_service.get_quote(symbol)
        print(f"SUCCESS: {quote}")
        # limit_price가 없으면 last * 1.01로 설정
        if limit_price is None:
            limit_price = quote.last * 1.01
            print(f"INFO: limit_price 자동 설정 (last * 1.01): {limit_price:.2f}")
    except Exception as e:
        print(f"FAIL: 시세 조회 실패: {e}")
        sys.exit(1)

    client._smart_sleep()
    
    print(f"--- [2/3] 매수 주문: {symbol}, qty={qty}, price={limit_price:.2f} ---")
    try:
        # side="buy" (매수)
        order_result = order_service.submit_order(symbol, qty, limit_price, "buy")
        print(f"SUCCESS: {order_result}")
    except Exception as e:
        print(f"FAIL: 주문 실패: {e}")
        sys.exit(1)

    client._smart_sleep()

    print(f"--- [3/3] 잔고 및 체결 조회 ---")
    try:
        balances = account_service.get_balance()
        print(f"SUCCESS: Balance count={len(balances)}")
        for b in balances:
            print(f"  - {b}")
            
        # 체결 내역 (오늘)
        fills = account_service.get_fills()
        print(f"SUCCESS: Fills count={len(fills)}")
        for f in fills:
            print(f"  - {f}")
            
    except Exception as e:
        print(f"FAIL: 잔고/체결 조회 실패: {e}")
        sys.exit(1)

    print("--- 스모크 테스트 완료 ---")


def main():
    parser = argparse.ArgumentParser(description="KIS 스모크 테스트 (시세->주문->잔고)")
    parser.add_argument("--symbol", type=str, required=True, help="테스트할 심볼 (예: AAPL)")
    parser.add_argument("--qty", type=int, default=1, help="주문 수량 (기본: 1)")
    parser.add_argument("--limit", type=float, help="지정가 (없으면 현재가 * 1.01)")
    
    args = parser.parse_args()
    
    run_flow(args.symbol, args.qty, args.limit)


if __name__ == "__main__":
    main()
