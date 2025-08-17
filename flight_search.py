# -*- coding: utf-8 -*-
# python flight_search.py

from amadeus import Client, ResponseError, Location
from dotenv import load_dotenv  # type: ignore
import os
from typing import Any
from pathlib import Path
from datetime import datetime, timezone, timedelta
import csv
import statistics as stats

load_dotenv()

# hostname: "test" 또는 "production"
amadeus = Client(
    client_id=os.getenv("AMADEUS_CLIENT_ID"),
    client_secret=os.getenv("AMADEUS_CLIENT_SECRET"),
    hostname=os.getenv("AMADEUS_HOSTNAME", "test"),
)

DATA_DIR = Path(__file__).with_name("data")

# 🇰🇷 한국 LCC IATA 코드
KOREAN_LCC = ["7C", "LJ", "TW", "BX", "RS", "ZE", "RF"]

def _csv_path(origin: str, dest: str, airline: str) -> Path:
    DATA_DIR.mkdir(exist_ok=True)
    name = f"prices_{origin.lower()}-{dest.lower()}_{airline.lower()}.csv"
    return DATA_DIR / name

def append_price_row(path: Path, row: dict) -> None:
    header = ["collected_at_utc","travel_date","origin","dest","airline",
              "flight_no","dep_time","arr_time","stops","duration","price","currency"]
    is_new = not path.exists()
    with path.open("a", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=header)
        if is_new:
            w.writeheader()
        w.writerow(row)

def rolling_avg(path: Path, days: int = 7) -> float | None:
    if not path.exists():
        return None
    since = datetime.now(timezone.utc) - timedelta(days=days)
    prices = []
    with path.open("r", newline="", encoding="utf-8") as f:
        r = csv.DictReader(f)
        for rec in r:
            try:
                ts = datetime.fromisoformat(rec["collected_at_utc"])
                if ts >= since:
                    prices.append(float(rec["price"]))
            except Exception:
                continue
    return stats.mean(prices) if prices else None

def print_offer(idx: int, o: dict[str, Any]) -> None:
    price = o["price"]["grandTotal"]
    currency = o["price"]["currency"]
    it = o["itineraries"][0]
    segs = it["segments"]
    dep = segs[0]["departure"]
    arr = segs[-1]["arrival"]
    dep_time = dep["at"]
    arr_time = arr["at"]
    dep_airport = dep["iataCode"]
    arr_airport = arr["iataCode"]
    carrier = segs[0]["carrierCode"]
    flight_no = f'{carrier}{segs[0]["number"]}'
    duration = it.get("duration", "")
    stops = len(segs) - 1

    print(
        f"[{idx}] {carrier} {dep_airport}→{arr_airport}  {dep_time} → {arr_time}  "
        f"{'직항' if stops == 0 else f'경유 {stops}회'}  {duration}  "
        f"{flight_no}  {price} {currency}"
    )

def group_cheapest_by_airline(offers: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """오퍼들을 항공사 코드별 최저가 한 건으로 묶는다(첫 구간 carrierCode 기준)."""
    cheapest: dict[str, dict[str, Any]] = {}
    for o in offers:
        try:
            segs = o["itineraries"][0]["segments"]
            carrier = segs[0]["carrierCode"]
            price = float(o["price"]["grandTotal"])
        except Exception:
            continue
        if carrier not in cheapest or price < float(cheapest[carrier]["price"]["grandTotal"]):
            cheapest[carrier] = o
    return cheapest

def main():
    # ▼ 필요 시 수정: 경로/날짜
    origin = "ICN"
    dest = "NRT"           # 하네다=HND
    travel_date = "2025-08-15"

    # 1) (옵션) 도쿄 권역 공항 몇 개만 표시
    try:
        r_loc = amadeus.reference_data.locations.get(keyword="TYO", subType=Location.AIRPORT)
        print(f"[Locations] 결과 {len(r_loc.data)}건 (예시 3건)")
        for item in r_loc.data[:3]:
            print("-", item.get("iataCode"), item.get("name"))
    except ResponseError as e:
        print("Locations 오류:", e)

    # 2) 한국 LCC 전체를 한 번에 검색 후, 항공사별 최저가 추출
    params = {
        "originLocationCode": origin,
        "destinationLocationCode": dest,
        "departureDate": travel_date,
        "adults": 1,
        "currencyCode": "KRW",
        "includedAirlineCodes": ",".join(KOREAN_LCC),
        "max": 200,  # 넉넉히
    }
    try:
        r = amadeus.shopping.flight_offers_search.get(**params)
        offers: list[dict[str, Any]] = r.data or []

        if not offers:
            print("검색 결과가 없습니다. 날짜/목적지/호스트(test/production)를 바꿔보세요.")
            return

        # 항공사별 최저가 하나씩
        by_airline = group_cheapest_by_airline(offers)

        # KOREAN_LCC 순서대로 출력/저장 (결과에 없는 항공사는 건너뜀)
        for code in KOREAN_LCC:
            o = by_airline.get(code)
            if not o:
                continue

            # 콘솔 출력(항공사별 1줄)
            print_offer(1, o)

            # CSV 저장 + 7일 평균/알림 체크
            it = o["itineraries"][0]; segs = it["segments"]
            dep, arr = segs[0]["departure"], segs[-1]["arrival"]
            flight_no = f'{segs[0]["carrierCode"]}{segs[0]["number"]}'
            row = {
                "collected_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                "travel_date": travel_date,
                "origin": origin,
                "dest": dest,
                "airline": code,
                "flight_no": flight_no,
                "dep_time": dep["at"],
                "arr_time": arr["at"],
                "stops": len(segs) - 1,
                "duration": it.get("duration",""),
                "price": float(o["price"]["grandTotal"]),
                "currency": o["price"]["currency"],
            }
            csv_path = _csv_path(origin, dest, code)
            append_price_row(csv_path, row)

            avg7 = rolling_avg(csv_path, days=7)
            if avg7 is not None:
                threshold = avg7 * 0.8
                if row["price"] <= threshold:
                    print(f"[{code}] 알림조건 충족: 현재가 {row['price']:.0f} ≤ 최근7일 평균의 80%({threshold:.0f})")
            else:
                print(f"[{code}] 최근 7일 평균 없음(초기 수집 중)")

    except ResponseError as e:
        print("Flight Offers Search 오류:", e)

if __name__ == "__main__":
    main()
