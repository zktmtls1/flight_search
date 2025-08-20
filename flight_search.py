from amadeus import Client, ResponseError
from dotenv import load_dotenv  # .env 파일에서 환경변수를 불러오기 위한 라이브러리
import os
from typing import Any, Dict, List
from pathlib import Path
from datetime import datetime, timezone
import csv
########## email을 통한 할인 알림 라이브러리 ########################
import smtplib
from email.mime.text import MIMEText
#################################################################

# .env 파일에 있는 환경변수(예: AMADEUS_CLIENT_ID 등)를 현재 프로세스에 로드
load_dotenv()

# Amadeus 클라이언트 생성
# - hostname: "test"(샌드박스) 또는 "production"(실데이터)
amadeus = Client(
    client_id=os.getenv("AMADEUS_CLIENT_ID"),
    client_secret=os.getenv("AMADEUS_CLIENT_SECRET"),
    hostname=os.getenv("AMADEUS_HOSTNAME", "test"),
)

# 데이터 저장 디렉터리 설정 (현재 파일과 같은 폴더에 data/ 생성)
DATA_DIR = Path(__file__).with_name("data")
DATA_DIR.mkdir(exist_ok=True)

def csv_path(origin: str, dest: str, airline: str) -> Path:
    """
    항공사별 CSV 파일 경로 생성
    예) data/prices_icn-nrt_7c.csv
    """
    return DATA_DIR / f"prices_{origin.lower()}-{dest.lower()}_{airline.lower()}.csv"

def append_row(path: Path, row: Dict[str, Any]) -> None: #키: 문자열
    """
    한 행(row)을 CSV에 추가.
    - 파일이 처음 생성될 때 헤더를 먼저 씀
    - 컬럼 스키마는 고정 (아래 header 순서 유지)
    """
    header = [
        "collected_at_utc","travel_date","origin","dest","airline",
        "flight_no","dep_time","arr_time","stops","duration","price","currency"
    ]
    is_new = not path.exists()
    with path.open("a", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=header)
        if is_new: #파일이 없다면 header생성, 있다면 데이터 행추가
            w.writeheader()
        w.writerow(row)

def _get_last_row(path: Path) -> dict[str, str] | None:
    if not path.exists():
        return None
    with path.open("r", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
        return rows[-1] if rows else None
    
def _rows_equivalent(last: dict[str, str], new: dict[str, Any]) -> bool:
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


def is_duplicate_last(path: Path, row: dict[str, Any]) -> bool:
    last = _get_last_row(path)
    if not last:
        return False
    return _rows_equivalent(last, row)

########################################### email 발송관련 함수 ################################################
def compare_last_two_prices(path: Path, airline: str, email_receiver: str) -> None:
    """
    CSV 파일에서 마지막 2개의 가격을 비교
    """
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
    if last_price > prev_price:
        msg = f"{airline} 가격 상승: {prev_price:.0f} → {last_price:.0f}"
        send_email(f"[항공권 가격 알림] {airline}", msg, email_receiver)
    elif last_price < prev_price:
        msg = f"{airline} 가격 하락: {prev_price:.0f} → {last_price:.0f}"
        send_email(f"[항공권 가격 알림] {airline}", msg, email_receiver)
    else:
        msg = f"{airline} 가격 동일: {last_price:.0f}"
    print(msg)
    

def send_email(subject: str, body: str, receiver: str) -> None:
    """
    email을 통해 가격 변동정보를 송신
    """
    sender = os.getenv("EMAIL_SENDER")
    password = os.getenv("EMAIL_PASSWORD")
    if not sender or not password or not receiver:
        print("이메일 환경 변수가 설정되지 않았습니다.")
        return
    msg = MIMEText(body, "plain", "utf-8")
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
##########################################################################################################







def main():
    # 검색 파라미터(노선/날짜/항공사)
    origin = "ICN"             # 출발: 인천
    dest = "NRT"               # 도착: 나리타 (하네다는 HND)
    travel_date = "2025-08-25" # 여정 날짜(YYYY-MM-DD)

    # - KE: 대한항공, OZ: 아시아나, YP: 에어프레미아
    # - 7C: 제주, TW: 티웨이, LJ: 진에어, ZE: 이스타, RS: 에어서울, BX: 에어부산
    lcc_codes = ["KE","OZ","7C","TW","LJ","ZE","RS","BX","YP"]

    # Amadeus Flight Offers Search 파라미터
    params = {
        "originLocationCode": origin, # 출발
        "destinationLocationCode": dest, # 도착
        "departureDate": travel_date,
        "adults": 1,
        "currencyCode": "KRW",
        "includedAirlineCodes": ",".join(lcc_codes), #항공사 목록
        "max": 250,  # 최대 반환 오퍼 수 (상한 늘리면 쿼터/시간 사용량 증가 가능)
    }
    ############################ email 발송관련 함수 ######################################
    email_receiver = "zktmtls1@naver.com"
    ############################################################
    try:
        # 항공권 검색 요청
        r = amadeus.shopping.flight_offers_search.get(**params)
        offers: List[Dict[str, Any]] = r.data or []  ### None 가져올 때 방어용 빈 리스트,  [str, Any]: 키 형식은 srt, 값 형식은 아무거나
        if not offers:
            print("검색 결과가 없습니다.")
            return

        # 항공사별로 '최저가' 한 건만 남기기 위한 딕셔너리
        best: Dict[str, Dict[str, Any]] = {}
        for o in offers:
            it = o["itineraries"][0] # 출국편
            segs = it["segments"] #전체 항공편들
            airline = segs[0]["carrierCode"]  # 항공사 코드 사용 (경유 있다면 첫 항공편)
            if airline not in lcc_codes:
                # 포함하지 않기로 한 항공사라면 스킵
                continue
            price = float(o["price"]["grandTotal"])

            # 해당 항공사 코드로 아직 선택된 오퍼가 없거나,
            # 현재 오퍼의 가격이 기존 최저가보다 낮으면 갱신
            if (airline not in best) or (price < float(best[airline]["price"]["grandTotal"])):
                best[airline] = o

        # 현재(UTC) 타임스탬프: 수집 시각 기록용
        now_utc = datetime.now(timezone.utc).isoformat(timespec="seconds")

        # 항공사 코드 정렬 후, 각 항공사별 최저가를 CSV에 한 줄씩 저장
        for al, o in sorted(best.items()):
            it = o["itineraries"][0]
            segs = it["segments"]
            dep = segs[0]["departure"]
            arr = segs[-1]["arrival"]

            # CSV 한 행 구성
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
                "duration": it.get("duration",""),  # ISO8601 기간 문자열(예: "PT2H20M")
                "price": float(o["price"]["grandTotal"]),
                "currency": o["price"]["currency"],
            }

            path = csv_path(origin, dest, al)
            if is_duplicate_last(path, row):
                print(f"{al}: 동일 데이터 감지, 저장/이메일 생략")
                continue
            append_row(path, row)
            print(f"{al}: {row['price']:.0f} {row['currency']} 저장됨")
            #################### 가격 비교 기능 실행 #########################################
            compare_last_two_prices(csv_path(origin, dest, al), al, email_receiver)
            ###############################################################################
    except ResponseError as e:
        # Amadeus SDK 예외 처리(HTTP 오류/쿼터 초과/파라미터 오류 등)
        print("Flight Offers Search 오류:", e)

if __name__ == "__main__":
    main()
