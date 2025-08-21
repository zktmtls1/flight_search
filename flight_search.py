from amadeus import Client, ResponseError
from dotenv import load_dotenv  
import os
from typing import Any, Dict, List, Optional
from pathlib import Path 
from datetime import datetime, timezone 
import csv

import json 
from pathlib import Path
import smtplib 
import pandas
from email.mime.text import MIMEText

load_dotenv()

amadeus = Client(
    client_id=os.getenv("AMADEUS_CLIENT_ID"),
    client_secret=os.getenv("AMADEUS_CLIENT_SECRET"),
    hostname=os.getenv("AMADEUS_HOSTNAME", "test"),
)

DATA_DIR = Path(__file__).with_name("data")
DATA_DIR.mkdir(exist_ok=True)



def csv_path(origin: str, dest: str, airline: str, travel_date: str) -> Path:
    return DATA_DIR / f"prices_{origin.lower()}-{dest.lower()}_{airline.lower()}_{travel_date}.csv"

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

def _get_last_row(path: Path) -> Optional[Dict[str, str]]:
    if not path.exists():
        return None
    with path.open("r", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
        return rows[-1] if rows else None 


def _rows_equivalent(last: Dict[str, str], new: Dict[str, Any]) -> bool:
    keys = ["travel_date","origin","dest","airline","flight_no","dep_time",
            "arr_time","stops","duration","price","currency"]
    for k in keys:
        lv = last.get(k)
        nv = new.get(k)
        if k == "price":
            if abs(float(lv) - float(nv)) > 0.0001:
                return False
                
        elif k == "stops":
            if int(lv) != int(nv):
                return False
        else: 
            if str(lv) != str(nv):
                return False
    return True


def is_duplicate_last(path: Path, row: Dict[str, Any]) -> bool:
    last = _get_last_row(path)
    if not last:
        return False
    return _rows_equivalent(last, row)


def search_flights(
    *,
    originLocationCode: str,   
    destinationLocationCode: str,  
    departureDate: str,
    adults: int = 1,
    airlineCode: str = "",
    currencyCode: str = "KRW",
    max_results: int = 5,
):
    params = {
        "originLocationCode": originLocationCode,
        "destinationLocationCode": destinationLocationCode,
        "departureDate": departureDate,
        "adults": adults,
        "currencyCode": currencyCode,
        "max": 250,
    }

    if airlineCode:
        params["includedAirlineCodes"] = airlineCode 

    r = amadeus.shopping.flight_offers_search.get(**params)
    offers = r.data or [] 
    offers.sort(key=lambda o: float(o["price"]["grandTotal"]))
    return offers[:max_results] 


def search_lowest_fares(
    *,
    originLocationCode: str,
    destinationLocationCode: str,
    departureDate: str,
    adults: int = 1,
    airlineCodes: Optional[List[str]] = None,
    currencyCode: str = "KRW",
):

    params = {
        "originLocationCode": originLocationCode,
        "destinationLocationCode": destinationLocationCode,
        "departureDate": departureDate,
        "adults": adults,
        "currencyCode": currencyCode,
        "max": 250, 
    }
    if airlineCodes:
        params["includedAirlineCodes"] = ",".join(airlineCodes)

    r = amadeus.shopping.flight_offers_search.get(**params)
    offers = r.data or []
    if not offers:
        return []

    best: Dict[str, Dict[str, Any]] = {}
    allow = set(airlineCodes) if airlineCodes else None
    for o in offers:
        try:
            it = o["itineraries"][0]   
            segs = it["segments"]  
            al = segs[0]["carrierCode"] 
            if allow and al not in allow:   
                continue
            price = float(o["price"]["grandTotal"]) 
            if (al not in best) or (price < float(best[al]["price"]["grandTotal"])): 
                best[al] = o
        except Exception:
            continue
    if not best:
        return []


    now_utc = datetime.now(timezone.utc).isoformat(timespec="seconds")
    rows = []
    for al, o in sorted(best.items()):
        it = o["itineraries"][0]
        segs = it["segments"]
        dep = segs[0]["departure"]
        arr = segs[-1]["arrival"]
        row = {
            "collected_at_utc": now_utc,
            "travel_date": departureDate,
            "origin": originLocationCode,
            "dest": destinationLocationCode,
            "airline": al,
            "flight_no": f"{segs[0]['carrierCode']}{segs[0]['number']}",
            "dep_time": dep["at"],
            "arr_time": arr["at"],
            "stops": len(segs) - 1,
            "duration": it.get("duration", ""),
            "price": float(o["price"]["grandTotal"]),
            "currency": o["price"]["currency"],
        }

        path = csv_path(originLocationCode, destinationLocationCode, al, departureDate)
        last = _get_last_row(path)
        stored = False
        prev_price = float(last["price"]) if last else None
        
        if (not last) or (not _rows_equivalent(last, row)):
            append_row(path, row)
            stored = True

        rows.append({
            "airline": al,
            "flight_no": row["flight_no"],
            "dep": dep.get("iataCode", ""),
            "arr": arr.get("iataCode", ""),
            "dep_time": row["dep_time"],
            "arr_time": row["arr_time"],
            "stops": row["stops"],
            "duration": row["duration"],
            "price": row["price"],
            "currency": row["currency"],
            "stored": stored,        
            "prev_price": prev_price,  
        })

    rows.sort(key=lambda x: x["price"])
    return rows



def find_two_prices(path: Path) -> None:
    if not path.exists():
        print("CSV 파일이 아직 없습니다.")
        return
    with path.open("r", encoding="utf-8") as f: 
        rows = list(csv.DictReader(f))
    if len(rows) < 2:
        print("가격 비교를 위해 최소 2개의 데이터가 필요합니다.")
        return
    last_price = float(rows[-1]["price"])
    prev_price = float(rows[-2]["price"])
    return last_price, prev_price


def convert_24_to_12_manual(hour:int, minute:int):
    period = "오전"
    if hour == 0:
        hour_12 = 12
    elif hour == 12:
        hour_12 = 12
        period = "오후"
    elif hour > 12:
        hour_12 = hour - 12
        period = "오후"
    else:
        hour_12 = hour
    return f"{period} {hour_12:02d}시 {minute:02d}분"


def send_email(
        origin:str,
        dest:str,
        travel_date:str,
        airline:str,
        flight_no:str,
        dep_time:str,
        arr_time:str,
        price:str,
        receiver:str
        ) -> None:
    
    sender = os.getenv("EMAIL_SENDER")
    password = os.getenv("EMAIL_PASSWORD")

    if not sender or not password or not receiver:
        print("이메일 환경 변수가 설정되지 않았습니다.")
        return
    
    airline_info = {
        "KE": ["대한항공", "https://www.koreanair.com/booking/search"],
        "OZ": ["아시아나항공", "https://flyasiana.com/C/KR/KO/index"],
        "7C": ["제주항공", "https://www.jejuair.net/ko/ibe/booking/Availability.do"],
        "TW": ["티웨이항공", "https://www.twayair.com/app/booking/searchItinerary"],
        "LJ": ["진에어", "https://www.jinair.com/booking/index"],
        "ZE": ["이스타항공", "http://xn--main-9b0s.eastarjet.com/search"],
        "RS": ["에어서울", "https://flyairseoul.com/I/ko/viewBooking.do"],
        "BX": ["에어부산", "https://www.airbusan.com/web/individual/booking/flightsAvail"],
        "YP": ["에어프레미아", "https://www.airpremia.com/a/ko/ticket/flight?IS_POINT=false"]
    }

    subject = f"[항공권 가격 인하!] {travel_date} / {origin} → {dest} / {airline_info[airline][0]}"

    dep_time_12 = convert_24_to_12_manual(int(dep_time[11:13]), int(dep_time[14:16]))
    arr_time_12 = convert_24_to_12_manual(int(arr_time[11:13]), int(arr_time[14:16]))

    html_body = f"""
        <html>
            <body>
                <p style="font-size:18px;">
                    {price}<br>
                    <br>
                    항공편 정보<br>
                    출발지 : {origin}<br>
                    도착지 : {dest}<br>
                    출발 시각 : {dep_time[:4]}년 {dep_time[5:7]}월 {dep_time[8:10]}일 {dep_time_12}<br>
                    도착 시각 : {arr_time[:4]}년 {arr_time[5:7]}월 {arr_time[8:10]}일 {arr_time_12}<br>
                    항공사 : {airline_info[airline][0]}({airline})<br>
                    기종 : {flight_no}<br>
                    놓치기 전에 서두르세요!
                </p>
            </body>
        </html>
        """
    
    msg = MIMEText(html_body, "html")
    msg["Subject"] = subject # 메일 제목 설정
    msg["From"] = sender
    msg["To"] = receiver
    try:
        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
            server.login(sender, password)
            server.sendmail(sender, receiver, msg.as_string())
        print("메일 발송 완료")
    except Exception as e:# 오류 발생 시
        print("메일 발송 오류:", e)

def load_cfg():
    p = Path(__file__).with_name("config.json")
    if p.exists():
        with p.open("r", encoding="utf-8") as f:
            return json.load(f)
    return {}



def main():
    cfg = load_cfg()
    
    origin        = cfg.get("origin", "ICN")
    dest          = cfg.get("dest", "NRT")
    travel_date   = cfg.get("travel_date", "2025-09-01")
    airline_list  = cfg.get("airline_codes", ["KE","OZ","7C","TW","LJ","ZE","RS","BX","YP"])
    currency      = "KRW"
    email_to      = cfg.get("email_to")         # 수신자(없으면 미발송)
    email_on      = bool(cfg.get("email_enabled", True))  # ← 토글(기본 ON)

    rows = search_lowest_fares(
        originLocationCode=origin,
        destinationLocationCode=dest,
        departureDate=travel_date,
        adults=1,
        airlineCodes=airline_list,
        currencyCode=currency,
    )
    if not rows:
        print("검색 결과가 없습니다.")
        return

    print(f"[최저가 요약] {origin}→{dest} {travel_date} / {len(rows)}개")
    for r in rows:
        print(
            f"{r['airline']} {r['flight_no']} "
            f"{r['dep_time']}→{r['arr_time']}  "
            f"stops:{r['stops']} ({r['duration']})  "
            f"{r['price']:.0f} {r['currency']}"
        )

    email_receiver = email_to
    for r in rows:
        path = csv_path(origin, dest, r["airline"], travel_date)
        
        if not path.exists():
            print(f"파일이 존재하지 않아 가격 비교를 건너뜁니다: {path}")
            continue

        prices = find_two_prices(path)
        if not prices:
            print(f"데이터가 부족하여 가격 비교를 건너뜁니다: {path}")
            continue

        if not r.get("stored"):
            print(f"가격 동결: {r['price']:,.0ff} KRW (신규 저장 없음)")
            continue
        
        last_price, prev_price = prices
        if last_price < prev_price:
            lowest_price = pandas.read_csv(path)["price"].min()
            price_msg = (
                f"가격 인하! : {prev_price:,.0f} KRW → {last_price:,.0f} KRW "
                f"/ 역대 최저가 : {lowest_price:,.0f} KRW"
            )
            print(price_msg)

            if email_on and email_to:
                send_email(
                    origin, dest, travel_date, r["airline"],
                    r["flight_no"], r["dep_time"], r["arr_time"],
                    price_msg, email_receiver
                )
        elif last_price > prev_price:
            print(f"가격 인상: {prev_price:,.0f} KRW → {last_price:,.0f} KRW")
        else:
            print(f"가격 동결: {prev_price:,.0f} KRW")
        
if __name__ == "__main__":
    main()
