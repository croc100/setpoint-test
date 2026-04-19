import os
import sys
import json
import datetime as dt
import re
import time
from typing import List, Dict
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup
import urllib3

# [환경 설정]
BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if BASE_DIR not in sys.path:
    sys.path.append(BASE_DIR)

RAW_TOURNAMENT_DIR = os.path.join(BASE_DIR, "data", "raw", "tournaments")
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

BASE_URL = "https://facecock.co.kr"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept-Language": "ko-KR,ko;q=0.9,en-US;q=0.8,en;q=0.7",
}

def _parse_date_string(text: str) -> str:
    """
    페이스콕 텍스트에서 시작일을 'YYYY-MM-DD' 형식으로 추출합니다.
    다양한 패턴 대응: 
    - "대회기간: 2026년 4월 11일~12일"
    - "대회기간2026년 4월 11일 ~ 2026년 4월 12일"
    - "25. 11. 29"
    """
    # 1순위: '2026년 4월 11일' 형태의 한글 포맷 파싱 (대회기간 라벨 유무 무관, 공백 유연하게 처리)
    match_ko = re.search(r"(\d{4})\s*년\s*(\d{1,2})\s*월\s*(\d{1,2})\s*일", text)
    if match_ko:
        year = match_ko.group(1)
        month = match_ko.group(2).zfill(2)
        day = match_ko.group(3).zfill(2)
        return f"{year}-{month}-{day}"

    # 2순위: '25. 11. 29' 형태의 점(.) 구분 포맷 파싱 (기존 로직 유지)
    # 날짜와 비슷해 보이는 텍스트(예: 25.11.29)를 찾음
    match_dot = re.search(r"(\d{2,4})\s*\.\s*(\d{1,2})\s*\.\s*(\d{1,2})", text)
    if match_dot:
        try:
            year = int(match_dot.group(1))
            if year < 100:  # '25' 처럼 두 자리 연도일 경우
                year += 2000
            month = str(int(match_dot.group(2))).zfill(2)
            day = str(int(match_dot.group(3))).zfill(2)
            return f"{year}-{month}-{day}"
        except Exception:
            pass

    return None

def fetch_tournament_list(page: int = 1) -> List[Dict]:
    """페이스콕 특정 페이지의 대회 목록 수집 (HTML 구조 완벽 반영)"""
    url = f"{BASE_URL}/page/index.php?onetable=&page={page}&pid=game&srows=&stx="
    tournaments = []
    
    try:
        resp = requests.get(url, headers=HEADERS, timeout=10, verify=False)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "lxml")
        
        # [SE Fix] 정확한 카드 컨테이너 타겟팅
        items = soup.select("div.multi-item")
        
        for item in items:
            # 1. 링크 및 ID, 대회명 추출 (h7 안의 a 태그)
            a_tag = item.select_one("h7 a")
            if not a_tag:
                continue
                
            href = a_tag.get("href", "")
            m = re.search(r"ga_id=(\d+)", href)
            if not m:
                continue
                
            external_id = m.group(1)
            external_url = urljoin(BASE_URL, href)
            name = a_tag.get_text(strip=True)
            
            # 2. 본문 텍스트 통째로 추출하여 파싱 (p.multi-cont)
            cont_tag = item.select_one("p.multi-cont")
            if not cont_tag:
                continue
                
            cont_text = cont_tag.get_text(separator="\n", strip=True)
            
            # --- 2-1. 지역 파싱 ---
            region_raw = ""
            region_match = re.search(r"\[(.*?)\]", cont_text)
            if region_match:
                region_raw = region_match.group(1).strip()
                rest_text = cont_text.split('\n')[0].replace(f"[{region_raw}]", "").strip()
                if rest_text:
                    region_raw = f"{region_raw} {rest_text}".strip()

            # --- 2-2. 날짜 파싱 ---
            start_date = _parse_date_string(cont_text)

            tournaments.append({
                "external_id": external_id,
                "name": name,
                "start_date": start_date,
                "region_raw": region_raw,
                "external_url": external_url,
                "source": "FACECOK"
            })
            
    except Exception as e:
        print(f"[!] 페이스콕 페이지 {page} 수집 중 에러 발생: {e}")
        
    return tournaments

def collect_tournaments(max_pages: int = 3):
    """대회 목록 수집 (단일 파일 저장 로직 제거, 리스트 반환)"""
    os.makedirs(RAW_TOURNAMENT_DIR, exist_ok=True)
    
    print(f"[*] 페이스콕(FACECOK) 대회 정보 수집 시작 (최대 {max_pages}페이지)...")
    all_tournaments = []
    
    for page in range(1, max_pages + 1):
        print(f"  [-] {page}페이지 수집 중...")
        page_data = fetch_tournament_list(page)
        if not page_data:
            print("  [-] 수집된 데이터가 없습니다. 루프를 종료합니다.")
            break 
        all_tournaments.extend(page_data)
        time.sleep(0.5)

    # 중복 제거 (external_id 기준)
    unique_tournaments = {t['external_id']: t for t in all_tournaments}.values()
    final_list = list(unique_tournaments)

    if not final_list:
        print("[!] 수집된 페이스콕 대회가 없습니다.")
        return [] # 빈 리스트 반환

    # 확인용 로그 출력
    print(f"\n[+] 수집된 첫 번째 대회 샘플: {final_list[0]['name']} | {final_list[0]['start_date']} | {final_list[0]['region_raw']}")

    # [핵심 변경 사항] 개별 JSON 파일 저장 로직을 제거하고, base.py로 데이터를 반환합니다.
    return final_list

if __name__ == "__main__":
    # 단독 실행 시 테스트 용도
    result = collect_tournaments()
    print(f"\n[Test] 단독 실행 결과: 총 {len(result)}개 대회 수집됨.")