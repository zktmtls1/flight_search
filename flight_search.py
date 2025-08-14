# -*- coding: utf-8 -*-
# python flight_search.py

from amadeus import Client, ResponseError, Location
from dotenv import load_dotenv  # type: ignore
import os
from typing import Any

load_dotenv()

# hostname: "test" 또는 "production"
amadeus = Client(
    client_id=os.getenv("AMADEUS_CLIENT_ID"),
    client_secret=os.getenv("AMADEUS_CLIENT_SECRET"),
    hostname=os.getenv("AMADEUS_HOSTNAME", "test"),
)

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

    except ResponseError as e:
        print("Flight Offers Search 오류:", e)

if __name__ == "__main__":
    main()
