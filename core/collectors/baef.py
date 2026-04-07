# core/collectors/baef.py
import datetime as dt
import re
import time
from typing import List, Optional, Tuple
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup
import urllib3

from core.models import Tournament, Source

# SSL 경고 무시
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/129.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "ko-KR,ko;q=0.9,en-US;q=0.8,en;q=0.7",
    "Referer": "https://www.badmintonfriends.co.kr/",
}

DATE_YMD_SLASH = re.compile(r"(\d{4})/(\d{1,2})/(\d{1,2})")
UUID_PATH = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$",
    re.IGNORECASE,
)

def _html_from_response(resp: requests.Response) -> str:
    return resp.content.decode("utf-8", errors="replace")

def _is_tournament_title(title: str) -> bool:
    """[핵심 1] 제목으로 대회 여부 판별 (노이즈 차단)"""
    blacklist = ["작성중", "공지", "안내", "채용", "이벤트", "상품", "수요조사", "패키지", "광고", "정보", "서비스", "비용", "메뉴얼", "안내서", "제작", "양식", "약관", "패치노트", "FAQ", "사진", "배프(배드민턴프렌즈)"]
    if any(b in title for b in blacklist):
        return False
        
    if re.search(r'제\s*\d+\s*회', title):
        return True
        
    whitelist = ["대회", "리그", "컵", "대잔치", "오픈", "축전"]
    if any(w in title for w in whitelist):
        return True
        
    return False

def _extract_info_from_text(html: str) -> Tuple[Optional[str], Optional[str]]:
    """[핵심 2] 순수 텍스트에서 날짜/장소 정밀 추출 (실패해도 예외처리)"""
    soup = BeautifulSoup(html, "lxml")
    lines = soup.get_text(separator="\n", strip=True).split("\n")
    
    start_date = None
    venue = None
    
    for i, line in enumerate(lines):
        if not start_date:
            m = DATE_YMD_SLASH.search(line)
            if m:
                try:
                    # 장고 DB에 넣기 위해 datetime.date 객체로 변환
                    start_date = dt.date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
                except ValueError:
                    pass
        
        if "장소" in line and not venue:
            parts = re.split(r'대회\s*장소|장소', line)
            if len(parts) > 1:
                candidate = parts[-1].strip()
                candidate = re.sub(r'^[:：\-\|•\s]+', '', candidate)
                candidate = re.sub(r'^\d+(-\d+)*\.?\s*', '', candidate)
                
                if len(candidate) > 1 and not re.match(r'^[\d\-\.\s]+$', candidate):
                    venue = candidate
            
            if not venue:
                for nxt_line in lines[i+1:i+5]:
                    candidate = re.sub(r'^[:：\-\|•\s]+', '', nxt_line.strip())
                    candidate = re.sub(r'^\d+(-\d+)*\.?\s*', '', candidate)
                    if len(candidate) > 1 and not re.match(r'^[\d\-\.\s]+$', candidate):
                        venue = candidate
                        break
                        
    return start_date, venue

def fetch_baef_tournament(url: str) -> Optional[Tournament]:
    resp = requests.get(url, headers=HEADERS, timeout=10, verify=False)
    resp.raise_for_status()

    html = _html_from_response(resp)
    soup = BeautifulSoup(html, "lxml")

    # 1. 제목 추출
    name = url
    h1 = soup.find("h1")
    if h1 and h1.get_text(strip=True):
        name = h1.get_text(strip=True)
    elif soup.title and soup.title.get_text(strip=True):
        name = soup.title.get_text(strip=True)

    # [적재 판별] 제목이 대회가 아니면 DB에 넣지 않음
    if not _is_tournament_title(name):
        return None

    # 2. 날짜/장소 정밀 추출
    start_date, venue = _extract_info_from_text(html)

    external_id = url.rstrip("/").split("/")[-1]

    # [반자동 적재] 날짜나 장소가 파싱되지 않아 None이어도 DB에 생성!
    obj, _created = Tournament.objects.update_or_create(
        source=Source.BAEF,
        external_id=external_id,
        defaults={
            "name": name,
            "start_date": start_date, 
            "end_date": start_date, # 단일 일자로 취급
            "region_raw": venue,    # 추출한 장소를 region_raw에 임시 적재
            "registration_start": None,
            "registration_end": None,
            "original_url": url,
        },
    )
    return obj

def _collect_detail_urls_from_list(list_url: str) -> List[str]:
    resp = requests.get(list_url, headers=HEADERS, timeout=10, verify=False)
    resp.raise_for_status()

    html = _html_from_response(resp)
    soup = BeautifulSoup(html, "lxml")

    detail_urls: set[str] = set()

    for a in soup.find_all("a", href=True):
        full = urljoin(list_url, a["href"])

        if not full.startswith("https://www.badmintonfriends.co.kr/"):
            continue

        path = full.split("https://www.badmintonfriends.co.kr/")[-1].lstrip("/")
        if UUID_PATH.fullmatch(path):
            detail_urls.add(full)

    return sorted(detail_urls)

def fetch_baef_from_list(list_url: str = "https://www.badmintonfriends.co.kr/contest") -> List[Tournament]:
    urls = _collect_detail_urls_from_list(list_url)
    results: List[Tournament] = []
    
    for url in urls:
        obj = fetch_baef_tournament(url)
        if obj:
            results.append(obj)
            print(f"[+] DB 적재 완료: {obj.name} (날짜: {obj.start_date}, 장소: {obj.region_raw})")
        time.sleep(0.1) # 서버 부하 방지
        
    return results