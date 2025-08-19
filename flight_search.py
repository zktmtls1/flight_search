# -*- coding: utf-8 -*-
# python flight_search.py

from amadeus import Client, ResponseError
from dotenv import load_dotenv  # type: ignore
import os
from typing import Any, Dict, List
from pathlib import Path
from datetime import datetime, timezone
import csv

load_dotenv()

amadeus = Client(
    client_id=os.getenv("AMADEUS_CLIENT_ID"),
    client_secret=os.getenv("AMADEUS_CLIENT_SECRET"),
    hostname=os.getenv("AMADEUS_HOSTNAME", "test"),
)

DATA_DIR = Path(__file__).with_name("data")
DATA_DIR.mkdir(exist_ok=True)

def csv_path(origin: str, dest: str, airline: str) -> Path:
    return DATA_DIR / f"prices_{origin.lower()}-{dest.lower()}_{airline.lower()}.csv"

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

def main():
    origin = "ICN"
    dest = "NRT"
    travel_date = "2025-08-25"
    lcc_codes = ["KE","OZ","7C","TW","LJ","ZE","RS","BX","YP"]

    params = {
        "originLocationCode": origin,
        "destinationLocationCode": dest,
        "departureDate": travel_date,
        "adults": 1,
        "currencyCode": "KRW",
        "includedAirlineCodes": ",".join(lcc_codes),
        "max": 250,
    }

    try:
        r = amadeus.shopping.flight_offers_search.get(**params)
        offers: List[Dict[str, Any]] = r.data or []
        if not offers:
            print("검색 결과가 없습니다.")
            return

        best: Dict[str, Dict[str, Any]] = {}
        for o in offers:
            it = o["itineraries"][0]
            segs = it["segments"]
            airline = segs[0]["carrierCode"]
            if airline not in lcc_codes:
                continue
            price = float(o["price"]["grandTotal"])
            if (airline not in best) or (price < float(best[airline]["price"]["grandTotal"])):
                best[airline] = o

        now_utc = datetime.now(timezone.utc).isoformat(timespec="seconds")
        for al, o in sorted(best.items()):
            it = o["itineraries"][0]
            segs = it["segments"]
            dep = segs[0]["departure"]
            arr = segs[-1]["arrival"]
            row = {
                "collected_at_utc": now_utc,
                "travel_date": travel_date,
                "origin": origin,
                "dest": dest,
                "airline": al,
                "flight_no": f'{segs[0]["carrierCode"]}{segs[0]["number"]}',
                "dep_time": dep["at"],
                "arr_time": arr["at"],
                "stops": len(segs) - 1,
                "duration": it.get("duration",""),
                "price": float(o["price"]["grandTotal"]),
                "currency": o["price"]["currency"],
            }
            append_row(csv_path(origin, dest, al), row)

    except ResponseError as e:
        print("Flight Offers Search 오류:", e)

if __name__ == "__main__":
    main()
