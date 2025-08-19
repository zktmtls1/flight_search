# -*- coding: utf-8 -*-
# python oneshot_year.py
"""
원샷 '월별' 최저가 수집 스크립트 (월당 최대 2콜: flight_dates 1 + offers 1)
환경변수:
  AMADEUS_CLIENT_ID=...
  AMADEUS_CLIENT_SECRET=...
  AMADEUS_HOSTNAME=test           # test | production
  ORIGIN=ICN
  DEST=NRT
  CURRENCY=KRW
  LCC_CODES=KE,OZ,7C,TW,LJ,ZE,RS,BX,YP  # 비우면 전체 항공사
  START_DATE=2025-08-20                 # 비우면 오늘
  MONTHS_AHEAD=12
  PER_CALL_SLEEP=0.2
"""
from amadeus import Client, ResponseError
from dotenv import load_dotenv  # type: ignore
import os, csv, time, calendar
from typing import Any, Dict, List, Optional, Tuple
from pathlib import Path
from datetime import datetime, timezone, date
# ---------------- 초기화 ----------------
load_dotenv()
amadeus = Client(
    client_id=os.getenv("AMADEUS_CLIENT_ID"),
    client_secret=os.getenv("AMADEUS_CLIENT_SECRET"),
    hostname=os.getenv("AMADEUS_HOSTNAME", "test"),  # "test" | "production"
)
ROOT = Path(__file__).parent
DATA_DIR = ROOT / "data"
DATA_DIR.mkdir(exist_ok=True)
# ---------------- CSV 유틸 ----------------
def csv_path(origin: str, dest: str) -> Path:
    # 월별 1줄씩 같은 파일에 누적
    return DATA_DIR / f"month_{origin.lower()}-{dest.lower()}_monthly.csv"
def append_row(path: Path, row: Dict[str, Any]) -> None:
    header = [
        "collected_at_utc","travel_date","origin","dest","airline",
        "flight_no","dep_time","arr_time","stops","duration","price","currency"
    ]
    is_new = not path.exists()
    with path.open("a", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=header)
        if is_new:
            w.writeheader()
        w.writerow(row)
# ---------------- 공용 유틸 ----------------
def parse_codes(s: Optional[str]) -> List[str]:
    if not s:
        return []
    return [c.strip().upper() for c in s.split(",") if c.strip()]
def call_offers(params: Dict[str, Any], retries: int = 3) -> List[Dict[str, Any]]:
    """Flight Offers Search - 429/5xx에 지수 백오프로 재시도"""
    backoff = 1.0
    for i in range(retries):
        try:
            r = amadeus.shopping.flight_offers_search.get(**params)
            return r.data or []
        except ResponseError as e:
            status = getattr(getattr(e, "response", None), "status_code", None)
            if status in (429, 500, 502, 503, 504) and i < retries - 1:
                time.sleep(backoff); backoff *= 2; continue
            raise
# ---------------- 월 범위 계산 ----------------
def first_day_of_month(d: date) -> date:
    return date(d.year, d.month, 1)
def last_day_of_month(d: date) -> date:
    return date(d.year, d.month, calendar.monthrange(d.year, d.month)[1])
def add_months(d: date, n: int) -> date:
    y = d.year + (d.month - 1 + n) // 12
    m = (d.month - 1 + n) % 12 + 1
    return date(y, m, 1)
# ---------------- 월 최저 날짜 (flight_dates 1콜) ----------------
def cheapest_day_in_month(origin: str, dest: str, month_start: date, month_end: date) -> Optional[Tuple[str, float]]:
    """
    shopping.flight_dates.get 사용해 월 범위 최저 '날짜'를 고른다.
    반환: (YYYY-MM-DD, 가격) 또는 None
    """
    # 콤마(,)로 범위 표기해야 함
    date_range = f"{month_start.isoformat()},{month_end.isoformat()}"
    try:
        r = amadeus.shopping.flight_dates.get(
            origin=origin,
            destination=dest,
            departureDate=date_range,
            # oneWay="true",  # 필요시 활성화
        )
        data = r.data or []
        best_date, best_price = None, None
        for item in data:
            price_obj = item.get("price") or {}
            price_text = price_obj.get("total") or price_obj.get("grandTotal") or price_obj.get("base")
            d = item.get("departureDate")
            if not (price_text and d):
                continue
            try:
                p = float(price_text)
            except:
                continue
            if best_price is None or p < best_price:
                best_price, best_date = p, d
        return (best_date, float(best_price)) if best_date else None
    except ResponseError as e:
        print(f"[flight_dates 실패] {origin}->{dest} {date_range} | {e}")
        return None
# ---------------- 메인 루프 (월별 1~2콜) ----------------
def run_oneshot_year():
    origin = os.getenv("ORIGIN", "ICN").upper()
    dest = os.getenv("DEST", "NRT").upper()
    currency = os.getenv("CURRENCY", "KRW").upper()
    airlines = parse_codes(os.getenv("LCC_CODES", ""))  # 비우면 전체
    start_str = os.getenv("START_DATE", "")
    start = date.fromisoformat(start_str) if start_str else date.today()
    months = int(os.getenv("MONTHS_AHEAD", "12"))
    sleep_s = float(os.getenv("PER_CALL_SLEEP", "0.2"))
    cur_month = first_day_of_month(start)
    out_path = csv_path(origin, dest)
    print(f"[월별 수집 시작] {origin}->{dest}, 시작월={cur_month}, 개월수={months}, 통화={currency}, 항공사={airlines or '전체'}")
    print(f"저장: {out_path}")
    for i in range(months):
        ms = add_months(cur_month, i)
        me = last_day_of_month(ms)
        ym = ms.strftime('%Y-%m')
        print(f"  - {ym} 범위: {ms} ~ {me}")
        # 1) 월 범위 최저 '날짜' (flight_dates 전용)
        pick = cheapest_day_in_month(origin, dest, ms, me)
        if not pick:
            print(f"    · {ym} | flight_dates 결과 없음(스킵)")
            time.sleep(sleep_s)
            continue
        best_date, _approx = pick
        print(f"    · 최저 날짜 후보: {best_date} (예상≈{_approx:.0f} {currency})")
        # 2) 그 날짜의 실제 오퍼에서 '전체 중 최저 1건' 저장
        params = {
            "originLocationCode": origin,
            "destinationLocationCode": dest,
            "departureDate": best_date,
            "adults": 1,
            "currencyCode": currency,
            "max": 250,
        }
        if airlines:
            params["includedAirlineCodes"] = ",".join(airlines)
        try:
            offers = call_offers(params)
            if not offers:
                print(f"    · {best_date} | 오퍼 없음")
                time.sleep(sleep_s)
                continue
            cheapest = min(offers, key=lambda o: float(o["price"]["grandTotal"]))
            it = cheapest["itineraries"][0]
            segs = it["segments"]
            dep = segs[0]["departure"]; arr = segs[-1]["arrival"]
            row = {
                "collected_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                "travel_date": best_date,
                "origin": origin,
                "dest": dest,
                "airline": segs[0]["carrierCode"],
                "flight_no": f'{segs[0]["carrierCode"]}{segs[0]["number"]}',
                "dep_time": dep["at"],
                "arr_time": arr["at"],
                "stops": len(segs) - 1,
                "duration": it.get("duration",""),
                "price": float(cheapest["price"]["grandTotal"]),
                "currency": cheapest["price"]["currency"],
            }
            append_row(out_path, row)
            print(f"    · 저장: {row['airline']} {row['price']:.0f} {row['currency']} (파일: {out_path.name})")
        except ResponseError as e:
            print(f"    · {best_date} | Flight Offers 오류: {e}")
        time.sleep(sleep_s)
    print("[월별 수집 완료]")
# ---------------- 실행 ----------------
if __name__ == "__main__":
    run_oneshot_year()
