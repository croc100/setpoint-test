import os
import sys
import json
import datetime as dt
import re
import time
from typing import List, Optional, Tuple, Dict
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup
import urllib3

# [환경 설정]
BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if BASE_DIR not in sys.path:
    sys.path.append(BASE_DIR)

# [경로 설정] 데이터 성격에 따른 저장소 분리
RAW_TOURNAMENT_DIR = os.path.join(BASE_DIR, "data", "raw", "tournaments")
RAW_PLAYER_DIR = os.path.join(BASE_DIR, "data", "raw", "players")

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/129.0.0.0 Safari/537.36",
    "Accept-Language": "ko-KR,ko;q=0.9,en-US;q=0.8,en;q=0.7",
    "Referer": "https://www.badmintonfriends.co.kr/",
}

UUID_PATH = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", re.IGNORECASE)

def _is_tournament_title(title: str) -> bool:
    blacklist = ["작성중", "공지", "안내", "채용", "이벤트", "상품", "수요조사", "패키지", "광고", "정보", "서비스", "비용", "메뉴얼", "안내서", "제작", "양식", "약관", "패치노트", "FAQ", "사진", "배프(배드민턴프렌즈)"]
    if any(b in title for b in blacklist): return False
    if re.search(r'제\s*\d+\s*회', title): return True
    whitelist = ["대회", "리그", "컵", "대잔치", "오픈", "축전"]
    return any(w in title for w in whitelist)

def _extract_info_from_oopy_json(html: str) -> Tuple[Optional[str], Optional[str], Optional[str]]:
    """
    [핵심 변경 사항]
    Next.js(__NEXT_DATA__) JSON을 뜯어서 '대회명', '일시', '장소'를 정확히 타겟팅하여 추출합니다.
    """
    soup = BeautifulSoup(html, "html.parser")
    script_tag = soup.find('script', id='__NEXT_DATA__')
    
    if not script_tag or not script_tag.string:
        return None, None, None

    try:
        data = json.loads(script_tag.string)
        blocks = data.get('props', {}).get('pageProps', {}).get('recordMap', {}).get('block', {})
    except json.JSONDecodeError:
        return None, None, None

    name, start_date, venue = None, None, None
    is_next_date = False
    is_next_venue = False

    # 노션 블록 순회 (정확한 텍스트 추출)
    for block_id, block_info in blocks.items():
        value = block_info.get('value', {})
        properties = value.get('properties', {})
        block_type = value.get('type', '')

        # 1. 대회명 추출 (페이지 최상단 h1)
        if block_type == 'page' and 'title' in properties and not name:
             name = properties['title'][0][0]

        if 'title' not in properties:
            continue
            
        text_data = properties['title'][0][0].strip()

        # 2. 날짜 추출 (서브 헤더 '대회일시' 바로 다음 불릿 리스트 텍스트)
        if "대회일시" in text_data:
            is_next_date = True
            continue
        if is_next_date and text_data:
            # "2026/05/17(일) 08:00 ~" 같은 텍스트에서 날짜만 정규식으로 안전하게 파싱
            date_match = re.search(r"(\d{4})/(\d{1,2})/(\d{1,2})", text_data)
            if date_match:
                start_date = f"{date_match.group(1)}-{date_match.group(2).zfill(2)}-{date_match.group(3).zfill(2)}"
            is_next_date = False

        # 3. 장소 추출 (서브 헤더 '대회장소' 바로 다음 불릿 리스트 텍스트)
        if "대회장소" in text_data:
            is_next_venue = True
            continue
        if is_next_venue and text_data:
            venue = text_data
            is_next_venue = False

    return name, start_date, venue

def fetch_tournament_to_dict(url: str) -> Optional[Dict]:
    """대회 기본 정보 수집"""
    try:
        resp = requests.get(url, headers=HEADERS, timeout=10, verify=False)
        resp.raise_for_status()
        
        # HTML 텍스트 전달
        html = resp.content.decode("utf-8", errors="replace")
        
        # JSON 기반 추출 함수 호출
        name, start_date, venue = _extract_info_from_oopy_json(html)

        if not name or not _is_tournament_title(name): 
            return None

        return {
            "external_id": url.rstrip("/").split("/")[-1],
            "name": name,
            "start_date": start_date,
            "end_date": start_date,   # BAEF는 단일 일정 → start = end
            "region_raw": venue,
            "external_url": url,
            "source": "BAEF"
        }
    except Exception as e:
        print(f"[!] 에러 {url}: {e}")
        return None

def fetch_player_stats_from_tournament(url: str) -> List[Dict]:
    """
    [확장 포인트] 해당 대회 페이지에서 플레이어 전적을 수집하는 로직
    """
    return []

def collect_tournaments(known_ids: set = None):
    """대회 목록 수집 (단일 파일 저장 로직 제거, 리스트 반환)"""
    known_ids = known_ids or set()
    os.makedirs(RAW_TOURNAMENT_DIR, exist_ok=True)
    list_url = "https://www.badmintonfriends.co.kr/contest"
    resp = requests.get(list_url, headers=HEADERS, timeout=10, verify=False)
    soup = BeautifulSoup(resp.text, "lxml")

    urls = sorted({urljoin(list_url, a["href"]) for a in soup.find_all("a", href=True)
                  if UUID_PATH.fullmatch(urljoin(list_url, a["href"]).split("/")[-1])})

    # 이미 수집된 UUID는 건너뜀
    urls = [u for u in urls if u.rstrip("/").split("/")[-1] not in known_ids]

    print(f"[*] BAEF 대회 정보 {len(urls)}개 수집 시작...")
    tournament_list = []

    for url in urls:
        res = fetch_tournament_to_dict(url)
        if res:
            tournament_list.append(res)
            print(f"  [+] 대회 수집 완료: {res['name']} | 일시: {res['start_date']} | 장소: {res['region_raw']}")
        time.sleep(0.1)

    # [핵심 변경 사항] 개별 JSON 파일 저장 로직을 제거하고, base.py로 데이터를 반환합니다.
    return tournament_list

def collect_player_stats():
    """플레이어 전적 수집 및 JSON 저장"""
    os.makedirs(RAW_PLAYER_DIR, exist_ok=True)
    print("[!] 플레이어 전적 수집 기능은 fetch_player_stats_from_tournament 구현 후 동작합니다.")

if __name__ == "__main__":
    # 단독 실행 시 테스트 용도 (반환값의 길이를 출력하여 정상 동작 확인)
    result = collect_tournaments()
    print(f"\n[Test] 단독 실행 결과: 총 {len(result)}개 대회 수집됨.")