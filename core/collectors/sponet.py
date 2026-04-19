from __future__ import annotations

import os
import sys
import json
import re
from datetime import datetime, timedelta, date
from typing import Any, Dict, List, Optional

import requests
import urllib3

# [환경 설정]
BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if BASE_DIR not in sys.path:
    sys.path.append(BASE_DIR)

RAW_TOURNAMENT_DIR = os.path.join(BASE_DIR, "data", "raw", "tournaments")
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# [SE Fix] 스포넷의 방어막을 우회하는 Vercel 프록시 API 사용
SPONET_API_BASE = "https://sponet-proxy.vercel.app/api"
SPONET_DETAIL_URL_TMPL = "https://ss-minton.netlify.app/sponettime/index.html?tournament={tid}"

HEADERS = {
    "Content-Type": "application/json",
    "Accept": "application/json",
}

def _parse_yyyymmdd_str(s: str) -> Optional[date]:
    s = (s or "").strip()
    if not s or len(s) != 8 or not s.isdigit():
        return None
    try:
        return datetime.strptime(s, "%Y%m%d").date()
    except ValueError:
        return None

def fetch_tournaments_from_proxy(limit: int = 100) -> List[Dict[str, Any]]:
    """Vercel Proxy API를 통해 스포넷 대회 리스트 가져오기"""
    url = f"{SPONET_API_BASE}/tournament-list"
    params = {
        "schGrade": "10",
        "GRADE": "",
        "pageStart": 0,
        "pageLimit": limit,
        "schTmNm": ""
    }

    try:
        response = requests.post(url, json=params, headers=HEADERS, timeout=15)
        response.raise_for_status()
        data = response.json()
        
        if data and "data_list" in data:
            return data["data_list"]
        return []
    except Exception as e:
        print(f"[!] 프록시 API 통신 오류: {e}")
        return []

def collect_tournaments(limit: int = 100, known_ids: set = None):
    """스포넷 대회 목록 수집 (단일 파일 저장 로직 제거, 리스트 반환)"""
    known_ids = known_ids or set()
    os.makedirs(RAW_TOURNAMENT_DIR, exist_ok=True)
    print(f"[*] 스포넷(SPONET) 대회 정보 수집 시작 (최근 {limit}개 대상, 프록시 경유)...")
    
    raw_tournaments = fetch_tournaments_from_proxy(limit=limit)
    if not raw_tournaments:
        print("[!] 수집된 스포넷 대회가 없습니다.")
        return [] # 빈 리스트 반환

    # [SE Fix] 모델 표준 스키마에 맞춘 이름 변경 (name, venue, region_raw 등)
    final_list = []
    seen_ids = set()
    now = datetime.now()
    
    # 1년 전 데이터까지만 수집 (필터링)
    threshold = now.date() - timedelta(days=365)

    for raw in raw_tournaments:
        tid = raw.get("TOURNAMENT_ID")
        if not tid or tid in seen_ids or str(tid) in known_ids:
            continue
            
        start_raw = raw.get("TOUR_DATE_FROM") or ""
        end_raw = raw.get("TOUR_DATE_TO") or ""
        
        start_dt = _parse_yyyymmdd_str(start_raw)
        end_dt = _parse_yyyymmdd_str(end_raw)
        
        # 날짜가 없거나 1년이 지난 과거 데이터는 패스
        if not start_dt or start_dt < threshold:
            continue

        seen_ids.add(tid)
        
        name = raw.get("TOURNAMENT_NM") or raw.get("TOUR_NAME") or ""
        venue = raw.get("TOUR_LOCATION") or ""
        
        final_list.append({
            "external_id": tid,
            "name": name,
            "start_date": start_dt.isoformat() if start_dt else None,
            "end_date": end_dt.isoformat() if end_dt else None,
            "region_raw": venue[:50], # 지역명을 별도로 주지 않으므로 장소를 자름
            "venue": venue,
            "external_url": SPONET_DETAIL_URL_TMPL.format(tid=tid),
            "source": "SPONET"
        })

    if not final_list:
        print("[!] 유효한 최신 대회 데이터가 없습니다.")
        return []

    # 최신순 정렬
    final_list.sort(key=lambda x: x["start_date"] or "1900-01-01", reverse=True)

    print(f"\n[+] 수집된 첫 번째 대회 샘플: {final_list[0]['name']} | {final_list[0]['start_date']} | {final_list[0]['venue'][:15]}")

    # [핵심 변경 사항] 개별 JSON 파일 저장 로직을 제거하고, base.py로 데이터를 반환합니다.
    return final_list

if __name__ == "__main__":
    # 단독 실행 시 테스트 용도
    result = collect_tournaments(limit=200)
    print(f"\n[Test] 단독 실행 결과: 총 {len(result)}개 대회 수집됨.")