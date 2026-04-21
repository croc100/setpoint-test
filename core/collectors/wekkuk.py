from __future__ import annotations

import os
import sys
import json
import datetime as dt
import re
import time
from dataclasses import dataclass
from datetime import date
from typing import List, Optional, Tuple

import requests
from bs4 import BeautifulSoup
import urllib3

# [환경 설정]
BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if BASE_DIR not in sys.path:
    sys.path.append(BASE_DIR)

RAW_TOURNAMENT_DIR = os.path.join(BASE_DIR, "data", "raw", "tournaments")
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

BASE_URL = "https://app2.wekkuk.com"
LIST_URL = f"{BASE_URL}/index.php/v2/contest_badminton/contest"

@dataclass
class RawTournament:
    source: str
    external_id: str
    name: str
    region_raw: str
    start_date: Optional[date]
    end_date: Optional[date]
    original_url: str
    venue: str = ""
    category: str = ""

_ONCLICK_ID_RE = re.compile(r"goto_contest_view\((\d+)\s*,")
# [SE Fix] 하이픈으로 파괴되지 않는 절대적인 날짜 추출 정규식
DATE_RE_SIMPLE = re.compile(r"(\d{4})[-./년\s]+(\d{1,2})[-./월\s]+(\d{1,2})")

def _extract_dates(text: str) -> tuple[Optional[date], Optional[date]]:
    matches = DATE_RE_SIMPLE.findall(text)
    if not matches:
        return None, None
    
    dates = []
    for y, m, d in matches:
        try:
            dates.append(date(int(y), int(m), int(d)))
        except ValueError:
            continue
            
    if not dates:
        return None, None
    
    dates.sort()
    return dates[0], dates[-1]

def _get_last_page_from_html(html: str) -> int:
    soup = BeautifulSoup(html, "lxml")
    last = 1
    pg_last = soup.select_one("paging li.pg_last")
    if pg_last and pg_last.get("onclick"):
        m = re.search(r"toPage\('(\d+)'", pg_last["onclick"])
        if m:
            return max(1, int(m.group(1)))
    for li in soup.select("paging li[onclick]"):
        onclick = li.get("onclick", "")
        m = re.search(r"toPage\('(\d+)'", onclick)
        if m:
            last = max(last, int(m.group(1)))
    return max(1, last)

def _find_wekkuk_info(soup: BeautifulSoup, keywords: List[str]) -> str:
    """위꾹 전용: 불순물 태그를 제거하고 순수 텍스트만 추출하는 초정밀 파서"""
    stems = soup.find_all("div", class_="gm-stem")
    for stem in stems:
        item_tag = stem.find("p", class_="gm-item")
        if not item_tag:
            continue
            
        # 순수 텍스트(TextNode)만 추출하여 노이즈 제거
        item_text = "".join(item_tag.find_all(string=True, recursive=False)).strip()
        
        if any(k in item_text for k in keywords):
            text_div = stem.find("div", class_="gm-text")
            if text_div:
                for span in text_div.find_all("span", class_="gm-color2"):
                    span.decompose() 
                val = text_div.get_text(" ", strip=True)
                return val[:100]
    return ""

def fetch_list(page: int, session: requests.Session) -> List[RawTournament]:
    params = {"page": str(page)}
    resp = session.get(LIST_URL, params=params, timeout=10, verify=False)
    resp.raise_for_status()

    soup = BeautifulSoup(resp.text, "lxml")
    tournaments: List[RawTournament] = []

    for card in soup.select(".game-list .gm-top"):
        onclick = card.get("onclick", "")
        m = _ONCLICK_ID_RE.search(onclick)
        if not m:
            continue
        bct_id = m.group(1)

        title_el = card.select_one(".gm-title")
        if not title_el:
            continue
        name = title_el.get_text(" ", strip=True)

        original_url = f"{BASE_URL}/index.php/v2/contest_badminton/contest/{bct_id}"

        start_date = None
        end_date = None
        venue = ""
        region_raw = ""
        try:
            time.sleep(0.3)
            detail_resp = session.get(original_url, timeout=10, verify=False)
            detail_soup = BeautifulSoup(detail_resp.text, "lxml")
            
            venue = _find_wekkuk_info(detail_soup, ["대회장소", "장소", "경기장"])
            region_raw = _find_wekkuk_info(detail_soup, ["개최지역", "지역"])
            
            # [수정] 깨지지 않는 날짜 추출 로직 적용
            raw_date_text = _find_wekkuk_info(detail_soup, ["대회기간", "대회 기간", "일시"])
            start_date, end_date = _extract_dates(raw_date_text)
            
        except Exception as e:
            print(f"  [!] 상세 페이지 추출 실패 (ID:{bct_id})")

        tournaments.append(
            RawTournament(
                source="WEEKUK",
                external_id=str(bct_id),
                name=name,
                region_raw=region_raw,
                start_date=start_date,
                end_date=end_date or start_date, 
                original_url=original_url,
                venue=venue,
                category="",
            )
        )
        print(f"  [-] 딥다이브 수집성공: ID {bct_id} | {start_date} | {venue[:15]}")

    return tournaments

def collect_tournaments(max_pages: int = 1, known_ids: set = None):
    """위꾹 대회 목록 수집 (단일 파일 저장 로직 제거, 리스트 반환)"""
    known_ids = known_ids or set()
    os.makedirs(RAW_TOURNAMENT_DIR, exist_ok=True)
    print(f"[*] 위꾹(WEEKUK) 대회 정보 수집 시작 (최대 {max_pages}페이지)...")

    session = requests.Session()
    session.headers.update({
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/120.0.0.0 Safari/537.36",
    })

    try:
        first = session.get(LIST_URL, params={"page": "1"}, timeout=10, verify=False)
        first.raise_for_status()
    except Exception as e:
        print(f"[!] 목록 접속 실패: {e}")
        return []

    last_page = _get_last_page_from_html(first.text)
    target_pages = min(last_page, max_pages) if max_pages > 0 else last_page

    all_tournaments: List[RawTournament] = []
    
    for p in range(1, target_pages + 1):
        print(f"  [-] {p}페이지 수집 중...")
        items = fetch_list(p, session)
        all_tournaments.extend(items)

    if not all_tournaments:
        print("[!] 수집된 위꾹 대회가 없습니다.")
        return []

    unique_items = {t.external_id: t for t in all_tournaments if t.external_id not in known_ids}.values()
    
    final_list = []
    for t in unique_items:
        final_list.append({
            "external_id": t.external_id,
            "name": t.name,
            "start_date": t.start_date.isoformat() if t.start_date else None,
            "end_date": t.end_date.isoformat() if t.end_date else None,
            "region_raw": t.region_raw,
            "venue": t.venue,
            "external_url": t.original_url,
            "source": t.source
        })

    if not final_list:
        print("[!] 모두 이미 수집된 위꾹 대회입니다 (증분 모드).")
        return []

    print(f"\n[+] 수집된 첫 번째 대회 샘플: {final_list[0]['name']} | {final_list[0]['start_date']} | {final_list[0]['venue'][:15]}")

    # [핵심 변경 사항] 개별 JSON 파일 저장 로직을 제거하고, base.py로 데이터를 반환합니다.
    return final_list

if __name__ == "__main__":
    # 단독 실행 시 테스트 용도
    result = collect_tournaments()
    print(f"\n[Test] 단독 실행 결과: 총 {len(result)}개 대회 수집됨.")