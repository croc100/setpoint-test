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

DATE_YMD_SLASH = re.compile(r"(\d{4})/(\d{1,2})/(\d{1,2})")
UUID_PATH = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", re.IGNORECASE)

def _is_tournament_title(title: str) -> bool:
    blacklist = ["작성중", "공지", "안내", "채용", "이벤트", "상품", "수요조사", "패키지", "광고", "정보", "서비스", "비용", "메뉴얼", "안내서", "제작", "양식", "약관", "패치노트", "FAQ", "사진", "배프(배드민턴프렌즈)"]
    if any(b in title for b in blacklist): return False
    if re.search(r'제\s*\d+\s*회', title): return True
    whitelist = ["대회", "리그", "컵", "대잔치", "오픈", "축전"]
    return any(w in title for w in whitelist)

def _extract_info_from_text(html: str) -> Tuple[Optional[str], Optional[str]]:
    soup = BeautifulSoup(html, "lxml")
    lines = soup.get_text(separator="\n", strip=True).split("\n")
    start_date, venue = None, None
    for i, line in enumerate(lines):
        if not start_date:
            m = DATE_YMD_SLASH.search(line)
            if m: start_date = f"{m.group(1)}-{m.group(2).zfill(2)}-{m.group(3).zfill(2)}"
        if "장소" in line and not venue:
            parts = re.split(r'대회\s*장소|장소', line)
            if len(parts) > 1:
                cand = re.sub(r'^[:：\-\|•\s]+', '', parts[-1].strip())
                if len(cand) > 1: venue = cand
    return start_date, venue

def fetch_tournament_to_dict(url: str) -> Optional[Dict]:
    """대회 기본 정보 수집"""
    try:
        resp = requests.get(url, headers=HEADERS, timeout=10, verify=False)
        resp.raise_for_status()
        html = resp.content.decode("utf-8", errors="replace")
        soup = BeautifulSoup(html, "lxml")
        
        name = soup.find("h1").get_text(strip=True) if soup.find("h1") else soup.title.get_text(strip=True)
        if not _is_tournament_title(name): return None

        start_date, venue = _extract_info_from_text(html)
        return {
            "external_id": url.rstrip("/").split("/")[-1],
            "name": name,
            "start_date": start_date,
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
    대회 상세 페이지 내의 '결과' 또는 '대진표' 데이터를 파싱하여 리스트로 반환
    """
    # TODO: 대진표/결과 API 또는 HTML 파싱 로직 구현
    # 예시 반환 구조:
    # return [{"player_name": "100", "club": "크로데", "rank": 1, ...}]
    return []

def collect_tournaments():
    """대회 목록 수집 및 JSON 저장"""
    os.makedirs(RAW_TOURNAMENT_DIR, exist_ok=True)
    list_url = "https://www.badmintonfriends.co.kr/contest"
    resp = requests.get(list_url, headers=HEADERS, timeout=10, verify=False)
    soup = BeautifulSoup(resp.text, "lxml")
    
    urls = sorted({urljoin(list_url, a["href"]) for a in soup.find_all("a", href=True) 
                  if UUID_PATH.fullmatch(urljoin(list_url, a["href"]).split("/")[-1])})
    
    print(f"[*] 대회 정보 {len(urls)}개 수집 시작...")
    tournament_list = []
    
    for url in urls:
        res = fetch_tournament_to_dict(url)
        if res:
            tournament_list.append(res)
            print(f"[+] 대회 수집: {res['name']}")
        time.sleep(0.1)

    # JSON 저장
    timestamp = dt.datetime.now().strftime('%Y%m%d_%H%M')
    out_path = os.path.join(RAW_TOURNAMENT_DIR, f"baef_tournaments_{timestamp}.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(tournament_list, f, ensure_ascii=False, indent=4)
    print(f"[*] 대회 저장 완료: {out_path}")

def collect_player_stats():
    """플레이어 전적 수집 및 JSON 저장 (별도 실행용)"""
    os.makedirs(RAW_PLAYER_DIR, exist_ok=True)
    # 수집 로직에 따라 위 collect_tournaments와 병합하거나 별도 루프 생성
    print("[!] 플레이어 전적 수집 기능은 fetch_player_stats_from_tournament 구현 후 동작합니다.")

if __name__ == "__main__":
    # 기본적으로 대회 정보부터 수집
    collect_tournaments()