import re
import time
import requests
from datetime import date
from bs4 import BeautifulSoup

BASE_URL = "https://facecock.co.kr"

def _parse_date_range(text: str):
    """
    텍스트에서 날짜 범위 추출. 
    정상적인 날짜가 파싱되지 않으면 None을 반환하여 '노이즈(공지사항)'로 취급.
    """
    if not text:
        return None, None
        
    # 특수문자를 모두 하이픈으로 통일 후 숫자만 추출
    clean_text = text.replace(".", "-").replace("/", "-").replace("년", "-").replace("월", "-").replace("일", "")
    nums = re.findall(r"\d+", clean_text)
    
    if len(nums) < 3:
        return None, None

    try:
        # 2자리 연도가 들어올 경우 2000을 더해줌 (예: 25 -> 2025)
        y = int(nums[0])
        y = y + 2000 if y < 100 else y
        start = date(y, int(nums[1]), int(nums[2]))

        if len(nums) >= 6:
            end_y = int(nums[3])
            end_y = end_y + 2000 if end_y < 100 else end_y
            end = date(end_y, int(nums[4]), int(nums[5]))
        elif len(nums) >= 4:
            end = date(y, int(nums[1]), int(nums[3]))
        else:
            end = start
            
        return start.isoformat(), end.isoformat()
    except Exception:
        return None, None

def _extract_table_value(soup: BeautifulSoup, label: str) -> str:
    """테이블 내 특정 라벨(예: 대회기간)의 값을 추출"""
    node = soup.find(string=re.compile(rf"\s*{label}\s*"))
    if not node:
        return ""
    
    cell = node.find_parent(["th", "td"])
    if not cell:
        return ""
        
    tr = cell.find_parent("tr")
    if not tr:
        return ""
        
    values = []
    for c in tr.find_all(["th", "td"], recursive=False):
        if node not in list(c.stripped_strings):
            txt = c.get_text(" ", strip=True)
            if txt:
                values.append(txt)
                
    return " ".join(values).strip()

def run_facecock_test():
    print("[*] 페이스콕 수집 테스트 시작 (구조적 필터링 적용)")
    session = requests.Session()
    session.headers.update({
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
    })
    
    # 테스트를 위해 1페이지만 조회
    list_url = f"{BASE_URL}/page/index.php?page=1&pid=game"
    print(f"[*] 접속 URL: {list_url}")
    
    resp = session.get(list_url, timeout=10)
    soup = BeautifulSoup(resp.text, "lxml")
    
    links = soup.find_all("a", href=re.compile(r"pid=game_view.*ga_id="))
    print(f"[*] 목록에서 찾은 링크 수: {len(links)}개\n")
    print("-" * 50)
    
    success_count = 0
    drop_count = 0
    
    for a in links:
        href = a.get("href", "")
        fallback_title = a.get_text(strip=True)
        m = re.search(r"ga_id=(\d+)", href)
        if not m:
            continue
            
        eid = m.group(1)
        detail_url = href if href.startswith("http") else (BASE_URL + href)
        
        # 상세 페이지 파싱
        try:
            d_resp = session.get(detail_url, timeout=10)
            dsoup = BeautifulSoup(d_resp.text, "lxml")
            
            period_raw = _extract_table_value(dsoup, "대회기간")
            start, end = _parse_date_range(period_raw)
            
            # [핵심 로직] 날짜가 파싱되지 않으면 '대회'가 아닌 공지사항/기타 글로 간주하고 버림
            if not start:
                print(f"[-] 드랍됨 (날짜 추출 실패) | 제목: {fallback_title}")
                drop_count += 1
                continue
                
            region = _extract_table_value(dsoup, "대회지역")
            venue = _extract_table_value(dsoup, "대회장소")
            
            print(f"[+] 수집 성공 | ID: {eid}")
            print(f"    - 제목: {fallback_title}")
            print(f"    - 기간: {start} ~ {end} (원본: {period_raw})")
            print(f"    - 지역: {region} / 장소: {venue}")
            
            success_count += 1
            time.sleep(0.2) # 서버 부하 방지
            
        except Exception as e:
            print(f"[!] 에러 발생 (ID: {eid}) | {e}")
            
    print("-" * 50)
    print(f"[*] 테스트 결과 요약")
    print(f"    - 총 탐색 링크: {len(links)}건")
    print(f"    - 정상 수집(대회): {success_count}건")
    print(f"    - 필터링됨(공지 등): {drop_count}건")

if __name__ == "__main__":
    run_facecock_test()