from amadeus import Client, ResponseError
from dotenv import load_dotenv  # api 키 등 환경변수 저장
import os #환경변수 읽기
from typing import Any, Dict, List, Optional
from pathlib import Path #경로 조작
from datetime import datetime, timezone #시간 처리
import csv
########## email을 통한 할인 알림 라이브러리 ########################
import smtplib #메일전송
import pandas
from email.mime.text import MIMEText #메일의 꾸미기
#################################################################

# .env 파일에 있는 환경변수(예: AMADEUS_CLIENT_ID 등)를 현재 프로세스에 로드
load_dotenv()

# Amadeus 클라이언트 생성
amadeus = Client(
    client_id=os.getenv("AMADEUS_CLIENT_ID"),
    client_secret=os.getenv("AMADEUS_CLIENT_SECRET"),
    hostname=os.getenv("AMADEUS_HOSTNAME", "test"),
)

# 데이터 저장 폴더 경로 설정
DATA_DIR = Path(__file__).with_name("data")
DATA_DIR.mkdir(exist_ok=True)




########################################### csv 생성, 데이터 저장 관련 함수 ################################################

##지정 경로에 항공사별 csv 생성
def csv_path(origin: str, dest: str, airline: str) -> Path:
    return DATA_DIR / f"prices_{origin.lower()}-{dest.lower()}_{airline.lower()}.csv"


##csv파일이 없다면 header생성, 있다면 데이터 행추가
def append_row(path: Path, row: Dict[str, Any]) -> None: #키: 문자열, 값: 아무 타입
    header = [
        "collected_at_utc","travel_date","origin","dest","airline",
        "flight_no","dep_time","arr_time","stops","duration","price","currency"
    ]
    is_new = not path.exists() #파일 존재 여부 논리
    with path.open("a", newline="", encoding="utf-8") as f: #파일 열기
        w = csv.DictWriter(f, fieldnames=header)
        if is_new: 
            w.writeheader() #csv 파일 없다면 헤더 추가
        w.writerow(row) #있다면 데이터 추가


## 데이터 추가 여부를 위해 csv 마지막 행 데이터 확인
def _get_last_row(path: Path) -> Optional[Dict[str, str]]:
    if not path.exists(): #파일 없다면
        return None
    with path.open("r", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
        return rows[-1] if rows else None #데이터가 있다면 마지막 행 가져오기
    

## 새 데이터가 마지막 데이터행과 동일한지 확인
def _rows_equivalent(last: Dict[str, str], new: Dict[str, Any]) -> bool:
    keys = ["travel_date","origin","dest","airline","flight_no","dep_time",
            "arr_time","stops","duration","price","currency"]
    for k in keys:
        lv = last.get(k)
        nv = new.get(k)
        if k == "price": #가격, 경유 횟수만 수로 비교 
            if abs(float(lv) - float(nv)) > 0.0001:
               return False
                
        elif k == "stops":
            if int(lv) != int(nv):
                return False
        else: #나머지 문자열 비교
            if str(lv) != str(nv):
                return False
    return True


##최종적으로 같으면 true, 다르면 false
def is_duplicate_last(path: Path, row: Dict[str, Any]) -> bool:
    last = _get_last_row(path)
    if not last: #저장된 기록 없으면
        return False 
    return _rows_equivalent(last, row) # 같으면 True 반환
#################################################################################################################





########################################### email 발송관련 함수 ################################################

## 새 데이터, 직전 데이터 가져옴(가격이 하락했으면 알람 발송 목표)
def find_two_prices(path: Path) -> None:
    if not path.exists():
        print("CSV 파일이 아직 없습니다.")
        return
    with path.open("r", encoding="utf-8") as f: #파일 오픈
        rows = list(csv.DictReader(f))
    if len(rows) < 2:
        print("가격 비교를 위해 최소 2개의 데이터가 필요합니다.")
        return
    last_price = float(rows[-1]["price"])
    prev_price = float(rows[-2]["price"]) 
    return last_price, prev_price


##24시 체제 12시로 변환
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


## 이메일 보내는 함수
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
    
    # 송신자 e-mail 정보 .env 파일에서
    sender = os.getenv("EMAIL_SENDER")
    password = os.getenv("EMAIL_PASSWORD")

    # 송신자 e-mail 또는 앱 비밀번호 또는 수신자 e-mail 정보가 없으면 오류 출력
    if not sender or not password or not receiver:
        print("이메일 환경 변수가 설정되지 않았습니다.")
        return
    
    # 각 항공사의 IATA 코드에 따른 항공사명과 url 주소를 저장
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

    # e-mail의 제목
    subject = f"[항공권 가격 인하!] {travel_date} / {origin} → {dest} / {airline_info[airline][0]}"

    #변환한 시간정보
    dep_time_12 = convert_24_to_12_manual(int(dep_time[11:13]), int(dep_time[14:16]))
    arr_time_12 = convert_24_to_12_manual(int(arr_time[11:13]), int(arr_time[14:16]))

    # HTML 형식의 메일 본문
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
                    url : {airline_info[airline][1]}<br><br>
                    놓치기 전에 서두르세요!
                </p>
            </body>
        </html>
        """
    
    # HTML 형식의 메일 본문을 담은 MIME 객체 생성
    msg = MIMEText(html_body, "html")
    msg["Subject"] = subject # 메일 제목 설정
    msg["From"] = sender     
    msg["To"] = receiver     
    try:
        # Gmail의 SMTP 서버에 SSL 방식으로 연결 (포트 465)
        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
            # 발신자 계정으로 로그인
            server.login(sender, password)
            # 메일 발송 (발신자, 수신자, 메일 내용)
            server.sendmail(sender, receiver, msg.as_string())
        print("메일 발송 완료")
    except Exception as e:# 오류 발생 시
        print("메일 발송 오류:", e)
#################################################################################################################




def main():
    # 검색 파라미터(출발,도착 공항/ 날짜 /항공사)
    origin = "ICN"   # 출발          
    dest = "NRT"          # 도착     
    travel_date = "2025-08-25" 

    # - KE: 대한항공, OZ: 아시아나, YP: 에어프레미아
    # - 7C: 제주, TW: 티웨이, LJ: 진에어, ZE: 이스타, RS: 에어서울, BX: 에어부산
    lcc_codes = ["KE","OZ","7C","TW","LJ","ZE","RS","BX","YP"]

    # Amadeus 검색 파라미터
    params = {
        "originLocationCode": origin, 
        "destinationLocationCode": dest, 
        "departureDate": travel_date,
        "adults": 1,
        "currencyCode": "KRW",
        "includedAirlineCodes": ",".join(lcc_codes), 
        "max": 250,  # 최대 반환 오퍼 수 (상한 늘리면 쿼터/시간 사용량 증가 가능)
    }
    try:
        r = amadeus.shopping.flight_offers_search.get(**params) # 항공권 검색 요청, r에 저장
        offers: List[Dict[str, Any]] = r.data or []  ### None 가져올 때 방어용 빈 리스트,  [str, Any]: 키 형식은 srt, 값 형식은 아무거나
        if not offers:
            print("검색 결과가 없습니다.")
            return

        # 항공사별로 '최저가' 한 건만 남기기 위한 딕셔너리
        best: Dict[str, Dict[str, Any]] = {}
        for o in offers:
            it = o["itineraries"][0] # 출국편도 (왕복이면 1)
            segs = it["segments"] #segments: 한 경로에 대한 도착지까지의 총 비행편 정보. 직항이면 1개, 경유라면 여러 비행편 정보 들어감
            airline = segs[0]["carrierCode"]  # 항공사 코드 (경유 있다면 첫 항공편의 항공사)
            if airline not in lcc_codes:
                # 포함하지 않기로 한 항공사라면 스킵
                continue
            price = float(o["price"]["grandTotal"])  # 세금 등 포함 최종 가격
            if (airline not in best) or (price < float(best[airline]["price"]["grandTotal"])): #항공사별 첫 정보이거나 최저가 갱신시 치환
                best[airline] = o
            

        # 현재(UTC) 타임스탬프: 수집 시각 기록용
        now_utc = datetime.now(timezone.utc).isoformat(timespec="seconds")

        # 항공사 코드 정렬 후, 각 항공사별 최저가를 CSV에 한 줄씩 저장
        for al, o in sorted(best.items()):
            it = o["itineraries"][0]
            segs = it["segments"]
            dep = segs[0]["departure"]
            arr = segs[-1]["arrival"]

            # CSV 구성
            row = {
                "collected_at_utc": now_utc,
                "travel_date": travel_date,
                "origin": origin,
                "dest": dest,
                "airline": al,
                "flight_no": f'{segs[0]["carrierCode"]}{segs[0]["number"]}',
                "dep_time": dep["at"],
                "arr_time": arr["at"],
                "stops": len(segs) - 1,             # 직항=0, 경유 횟수=(세그먼트-1)
                "duration": it.get("duration",""),  # 운행 시간 EX)"PT2H20M" = 2시간 20분 (ISO-8601 기간 표기)
                "price": float(o["price"]["grandTotal"]),
                "currency": o["price"]["currency"],
            }

            path = csv_path(origin, dest, al)
            last = _get_last_row(path)

            # 새 데이터가 직전과 동일할시 저장 생략
            if last and _rows_equivalent(last, row):
                print(f"{al}: 가격 동결: {float(last['price']):,.0f} KRW (변화 없음, 저장 생략)")
                continue

            # 다르면 저장
            append_row(path, row)
            print(f"{al}: {row['price']:.0f} {row['currency']} 저장됨")


            ########################################### email 발송 + ################################################
            email_receiver = "zktmtls1@naver.com"
            # 3) 이전가와 비교해 인하/인상 판단 (기존 find_two_prices 안 써도 됨)
            if last:
                prev_price = float(last["price"])
                last_price = float(row["price"])
                sale_price = prev_price - last_price

                if sale_price > 0:
                    lowest_price = pandas.read_csv(path)["price"].min()
                    price_msg = (
                        f"가격 인하! : {prev_price:,.0f} KRW → {last_price:,.0f} KRW "
                        f"/ 역대 최저가 : {lowest_price:,.0f} KRW"
                    )
                    print(price_msg)
                    send_email(
                        origin, dest, travel_date, al,
                        row["flight_no"], dep["at"], arr["at"],
                        price_msg, email_receiver
                    )
                elif sale_price < 0:
                    print(f"가격 인상: {prev_price:,.0f} KRW → {last_price:,.0f} KRW")
            ########################################################################################################

    except ResponseError as e:
        # Amadeus SDK 예외 처리(HTTP 오류/쿼터 초과/파라미터 오류 등)
        print("Flight Offers Search 오류:", e)

if __name__ == "__main__":
    main()
