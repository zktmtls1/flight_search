from dotenv import load_dotenv
import os
from typing import Any, Dict, List, Optional
from pathlib import Path
from datetime import datetime
import csv
import json
import smtplib
import pandas
from email.mime.text import MIMEText

# 이 스크립트는 GitHub Actions 환경에서 실행되며,
# 로컬에서 이미 수집된 CSV 파일을 기반으로 가격 변동을 감지하고 메일을 발송합니다.

# .env 파일에 있는 환경변수를 로드합니다.
load_dotenv()

# 데이터 저장 폴더 경로를 설정합니다.
DATA_DIR = Path(__file__).with_name("data")
# GitHub Actions에서는 이미 파일이 존재하므로 폴더를 생성할 필요는 없습니다.
# DATA_DIR.mkdir(exist_ok=True)


# -------------------- CSV 파일 처리 함수 --------------------

def csv_path(origin: str, dest: str, airline: str, travel_date: str) -> Path:
    """지정 경로에 항공사별, 날짜별 csv 경로를 반환합니다."""
    return DATA_DIR / f"prices_{origin.lower()}-{dest.lower()}_{airline.lower()}_{travel_date}.csv"


def _get_last_row(path: Path) -> Optional[Dict[str, str]]:
    """CSV 파일의 마지막 행 데이터를 반환합니다."""
    if not path.exists():
        return None
    with path.open("r", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
        return rows[-1] if rows else None
    

def find_two_prices(path: Path) -> Optional[tuple[float, float]]:
    """새로운 데이터와 직전 데이터를 가져와 가격을 비교합니다."""
    if not path.exists():
        print("CSV 파일이 아직 없습니다.")
        return None
    with path.open("r", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    if len(rows) < 2:
        print("가격 비교를 위해 최소 2개의 데이터가 필요합니다.")
        return None
    last_price = float(rows[-1]["price"])
    prev_price = float(rows[-2]["price"])
    return last_price, prev_price


# -------------------- 이메일 발송 관련 함수 --------------------

def convert_24_to_12_manual(hour:int, minute:int):
    """24시 체제를 12시로 변환합니다."""
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
    """실제 이메일을 발송하는 함수입니다."""
    
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
    msg["Subject"] = subject
    msg["From"] = sender
    msg["To"] = receiver
    try:
        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
            server.login(sender, password)
            server.sendmail(sender, receiver, msg.as_string())
        print("메일 발송 완료")
    except Exception as e:
        print("메일 발송 오류:", e)


# -------------------- 설정 파일 로드 함수 --------------------

def load_cfg():
    """config.json 파일을 로드합니다."""
    p = Path(__file__).with_name("config.json")
    if p.exists():
        with p.open("r", encoding="utf-8") as f:
            return json.load(f)
    return {}


# -------------------- 메인 실행 함수 --------------------

def main():
    cfg = load_cfg()
    
    # GitHub Actions에서 사용할 파라미터들
    origin       = cfg.get("origin", "ICN")
    dest         = cfg.get("dest", "NRT")
    travel_date  = cfg.get("travel_date", "2025-09-01")
    airline_list = cfg.get("airline_codes", ["KE","OZ","7C","TW","LJ","ZE","RS","BX","YP"])
    email_to     = cfg.get("email_to")
    email_on     = bool(cfg.get("email_enabled", True))

    print(f"[가격 알림 감지] {origin}→{dest} {travel_date}")
    
    if not email_on or not email_to:
        print("이메일 알림 기능이 비활성화되었거나 수신자가 설정되지 않았습니다.")
        return

    # 각 항공사별 CSV 파일을 확인하며 가격 변동을 감지합니다.
    for airline in airline_list:
        path = csv_path(origin, dest, airline, travel_date)
        
        # 파일이 존재하지 않거나 데이터가 2개 미만이면 건너뜁니다.
        if not path.exists():
            continue
        
        last_row = _get_last_row(path)
        if not last_row:
            continue
            
        prices = find_two_prices(path)
        if not prices:
            continue

        last_price, prev_price = prices
        
        # 가격이 하락했을 경우에만 메일을 보냅니다.
        if last_price < prev_price:
            lowest_price = pandas.read_csv(path)["price"].min()
            price_msg = (
                f"가격 인하! : {prev_price:,.0f} KRW → {last_price:,.0f} KRW "
                f"/ 역대 최저가 : {lowest_price:,.0f} KRW"
            )
            print(f"가격 인하 감지: {airline} - {price_msg}")

            send_email(
                origin, dest, travel_date, airline,
                last_row["flight_no"], last_row["dep_time"], last_row["arr_time"],
                price_msg, email_to
            )
        elif last_price > prev_price:
            print(f"가격 인상: {airline} - {prev_price:,.0f} KRW → {last_price:,.0f} KRW")
        else:
            print(f"가격 동결: {airline} - {prev_price:,.0f} KRW")

if __name__ == "__main__":
    main()
