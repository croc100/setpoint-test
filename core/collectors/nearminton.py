from __future__ import annotations

import os
import sys
import json
import datetime as dt
import re
import time
from dataclasses import dataclass
from datetime import date
from typing import List, Optional

import requests
from bs4 import BeautifulSoup
import urllib3

BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if BASE_DIR not in sys.path:
    sys.path.append(BASE_DIR)

RAW_TOURNAMENT_DIR = os.path.join(BASE_DIR, "data", "raw", "tournaments")
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

BASE_URL = "https://nearminton.com"
LIST_URL = f"{BASE_URL}/competition_list.php"

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

DATE_RE_SIMPLE = re.compile(r"(\d{4})-(\d{2})-(\d{2})")

def _find_strict_info(soup: BeautifulSoup, keywords: List[str]) -> str:
    """엄격한 테이블 구조(th, td, dt, dd)에서만 값을 가져오는 안전한 파서"""
    for tag in soup.find_all(["th", "dt"]):
        text = tag.get_text(strip=True)
        if any(k in text for k in keywords):
            sibling = tag.find_next_sibling(["td", "dd"])
            if sibling:
                # 텍스트가 너무 길면(50자 이상) 노이즈로 간주하고 자름
                val = sibling.get_text(" ", strip=True)
                return val[:50]
    return ""

def fetch_list() -> List[RawTournament]:
    session = requests.Session()
    session.headers.update({
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/120.0.0.0 Safari/537.36",
    })

    print("  [-] 목록 페이지 구조 분석 중...")
    try:
        resp = session.get(LIST_URL, timeout=10, verify=False)
        resp.raise_for_status()
    except Exception as e:
        print(f"  [!] 목록 접속 실패: {e}")
        return []

    soup = BeautifulSoup(resp.text, "lxml")
    tournaments: List[RawTournament] = []
    seen_ids = set()

    list_items = soup.find_all("div", class_="list flex")
    
    for item in list_items:
        if item.get("style") and "min-height" in item.get("style"):
            continue

        link_tag = item.find("a", href=re.compile(r"competition_view\.php\?idx="))
        if not link_tag:
            continue
            
        href = link_tag.get("href", "").strip()
        idx_match = re.search(r"idx=(\d+)", href)
        if not idx_match:
            continue
            
        external_id = idx_match.group(1)
        if external_id in seen_ids or external_id in known_ids:
            continue
        seen_ids.add(external_id)

        original_url = f"{BASE_URL}/{href.lstrip('/')}"
        strong_tag = link_tag.find("strong")
        name = strong_tag.get_text(strip=True) if strong_tag else link_tag.get_text(strip=True)

        # 1. 시작일: 목록의 "대회 시작일 : YYYY-MM-DD" 절대 신뢰
        list_start_date = None
        date_div = item.find("div", class_="date")
        if date_div:
            m = DATE_RE_SIMPLE.search(date_div.get_text())
            if m:
                try:
                    list_start_date = date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
                except ValueError:
                    pass

        # 2. 장소: 리스트 본문(<p>)에 있는 "장소 : OOO" 패턴 선제 추출
        list_venue = ""
        content_div = item.find("div", class_="content")
        if content_div:
            # 줄바꿈 문자를 살려서 텍스트 추출
            p_text = content_div.get_text(separator="\n")
            v_match = re.search(r"(?:장소|장 소)\s*:\s*([^\n]+)", p_text)
            if v_match:
                list_venue = v_match.group(1).strip()

        # 3. 상세 페이지 딥다이브 (장소를 못 찾았거나 추가 정보 필요 시)
        detail_venue = ""
        region_raw = ""
        try:
            time.sleep(0.2)
            detail_resp = session.get(original_url, timeout=10, verify=False)
            detail_soup = BeautifulSoup(detail_resp.text, "lxml")
            
            detail_venue = _find_strict_info(detail_soup, ["대회 장소", "경기장", "장소"])
            region_raw = _find_strict_info(detail_soup, ["지역", "개최지역"])
            
        except Exception as e:
            print(f"  [!] 상세 페이지 추출 실패 (ID:{external_id})")

        # 리스트에서 찾은 장소가 있으면 우선 사용, 없으면 상세페이지 값 사용
        final_venue = list_venue if list_venue else detail_venue

        tournaments.append(
            RawTournament(
                source="NEARMINTON",
                external_id=external_id,
                name=name,
                region_raw=region_raw,
                start_date=list_start_date, # 리스트 날짜 강제 고정
                end_date=list_start_date,   # 단일 일자로 1차 세팅
                original_url=original_url,
                venue=final_venue[:100],
            )
        )
        print(f"  [-] 수집성공: ID {external_id} | {list_start_date} | {final_venue[:15]}")

    return tournaments

def collect_tournaments(known_ids: set = None):
    """우동배 대회 목록 수집 (단일 파일 저장 로직 제거, 리스트 반환)"""
    known_ids = known_ids or set()
    os.makedirs(RAW_TOURNAMENT_DIR, exist_ok=True)
    print("[*] 우동배(NEARMINTON) 대회 정보 수집 시작...")
    
    all_tournaments = fetch_list()

    if not all_tournaments:
        print("[!] 수집된 우동배 대회가 없습니다.")
        return [] # 빈 리스트 반환

    final_list = []
    for t in all_tournaments:
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

    print(f"\n[+] 수집된 첫 번째 대회 샘플: {final_list[0]['name']} | {final_list[0]['start_date']} | {final_list[0]['venue']}")
    
    # [핵심 변경 사항] 개별 JSON 파일 저장 로직을 제거하고, base.py로 데이터를 반환합니다.
    return final_list

if __name__ == "__main__":
    # 단독 실행 시 테스트 용도
    result = collect_tournaments()
    print(f"\n[Test] 단독 실행 결과: 총 {len(result)}개 대회 수집됨.")