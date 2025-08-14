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

def _csv_path(origin: str, dest: str, airline: str) -> Path:
    DATA_DIR.mkdir(exist_ok=True)
    name = f"prices_{origin.lower()}-{dest.lower()}_{airline.lower()}.csv"
    return DATA_DIR / name

def append_price_row(path: Path, row: dict) -> None:
    # 헤더 보장 후 append
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

    # 수하물(가능 시)
    baggage = None
    for tp in o.get("travelerPricings", []):
        for fd in tp.get("fareDetailsBySegment", []):
            inc = fd.get("includedCheckedBags") or {}
            if "quantity" in inc:
                baggage = f'Checked x{inc["quantity"]}'
                break
            if "weight" in inc and "weightUnit" in inc:
                baggage = f'Checked {inc["weight"]}{inc["weightUnit"]}'
                break
        if baggage:
            break

    print(
        f"[{idx}] {dep_airport}→{arr_airport}  {dep_time} → {arr_time}  "
        f"{'직항' if stops == 0 else f'경유 {stops}회'}  {duration}  "
        f"{flight_no}  {price} {currency}"
        f"{'  | ' + (baggage or '') if baggage else ''}"
    )

def main():
    # 1) 도쿄 권역 공항 몇 개만 표시(옵션)
    try:
        r_loc = amadeus.reference_data.locations.get(
            keyword="TYO", subType=Location.AIRPORT
        )
        print(f"[Locations] 결과 {len(r_loc.data)}건 (예시 3건)")
        for item in r_loc.data[:3]:
            print("-", item.get("iataCode"), item.get("name"))
    except ResponseError as e:
        print("Locations 오류:", e)

    # 2) 항공권 검색(최저가 1건만 출력)
    params = {
        "originLocationCode": "ICN",
        "destinationLocationCode": "NRT",  # 하네다=HND
        "departureDate": "2025-08-15",
        "adults": 1,
        "currencyCode": "KRW",
        "includedAirlineCodes": "7C",      # 제주항공
        "max": 50,
    }
    try:
        r = amadeus.shopping.flight_offers_search.get(**params)
        offers = r.data

        if not offers:
            print("검색 결과가 없습니다. 날짜/목적지/호스트(test/production)를 바꿔보세요.")
            return

        # 최저가 1건만 출력
        cheapest = min(offers, key=lambda o: float(o["price"]["grandTotal"]))
        print_offer(1, cheapest)

            # 최저가 1건만 출력
        cheapest = min(offers, key=lambda o: float(o["price"]["grandTotal"]))
        print_offer(1, cheapest)

        # ---- 저장 + 평균/알림 로직 ----
        origin = params["originLocationCode"]
        dest = params["destinationLocationCode"]
        airline = params["includedAirlineCodes"]
        it = cheapest["itineraries"][0]; segs = it["segments"]
        dep, arr = segs[0]["departure"], segs[-1]["arrival"]
        flight_no = f'{segs[0]["carrierCode"]}{segs[0]["number"]}'
        row = {
            "collected_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "travel_date": params["departureDate"],
            "origin": origin,
            "dest": dest,
            "airline": airline,
            "flight_no": flight_no,
            "dep_time": dep["at"],
            "arr_time": arr["at"],
            "stops": len(segs) - 1,
            "duration": it.get("duration",""),
            "price": float(cheapest["price"]["grandTotal"]),
            "currency": cheapest["price"]["currency"],
        }
        csv_path = _csv_path(origin, dest, airline)
        append_price_row(csv_path, row)

        avg7 = rolling_avg(csv_path, days=7)
        if avg7 is not None:
            print(f"[요약] 최근 7일 평균가: {avg7:.0f} {row['currency']} | 현재가: {row['price']:.0f} {row['currency']}")
            threshold = avg7 * 0.8
            if row["price"] <= threshold:
                print(f"[알림조건 충족] 현재가가 평균의 80% 이하({threshold:.0f})입니다!")
        else:
            print("[요약] 과거 데이터가 없어 평균을 계산하지 않았습니다.")


    except ResponseError as e:
        print("Flight Offers Search 오류:", e)

if __name__ == "__main__":
    main()
