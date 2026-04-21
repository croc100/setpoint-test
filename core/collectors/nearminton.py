from __future__ import annotations

import os
import sys
import json
import re
import time
from dataclasses import dataclass, field
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

BASE_URL  = "https://nearminton.com"
LIST_URL  = f"{BASE_URL}/competition_list.php"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/120.0.0.0 Safari/537.36",
}

CODE_RE      = re.compile(r'/t/([A-Z0-9][A-Z0-9-]{3,})')   # /t/T26-HMJ4F
DATE_ISO_RE  = re.compile(r'(\d{4}-\d{2}-\d{2})')


@dataclass
class RawTournament:
    source:       str
    external_id:  str          # 우동배 코드 (예: "T26-HMJ4F")
    name:         str
    region_raw:   str
    start_date:   Optional[date]
    end_date:     Optional[date]
    original_url: str
    venue:        str = ""
    category:     str = ""


def _parse_iso_date(s: str) -> Optional[date]:
    m = DATE_ISO_RE.search(s or "")
    if not m:
        return None
    try:
        return date.fromisoformat(m.group(1))
    except ValueError:
        return None


def _extract_t_model(html: str) -> Optional[dict]:
    """
    페이지 HTML에서 `T_MODEL = {...}` 인라인 JSON을 파싱.
    없으면 None 반환.
    """
    m = re.search(r'T_MODEL\s*=\s*(\{.+?\})\s*;', html, re.DOTALL)
    if not m:
        return None
    try:
        return json.loads(m.group(1))
    except (json.JSONDecodeError, ValueError):
        return None


def _fetch_detail(session: requests.Session, code: str) -> Optional[RawTournament]:
    """
    /t/{code} 대회 상세 페이지에서 T_MODEL JSON으로 대회 정보 추출.
    """
    url = f"{BASE_URL}/t/{code}"
    try:
        r = session.get(url, headers=HEADERS, timeout=12, verify=False)
        r.raise_for_status()
    except Exception as e:
        print(f"  [!] 상세 페이지 실패 ({code}): {e}")
        return None

    model = _extract_t_model(r.text)
    if not model:
        # T_MODEL이 없으면 BeautifulSoup으로 최소 정보만 추출
        soup = BeautifulSoup(r.text, "lxml")
        name = soup.find("title")
        name = name.get_text(strip=True) if name else code
        return RawTournament(
            source="NEARMINTON",
            external_id=code,
            name=name,
            region_raw="",
            start_date=None,
            end_date=None,
            original_url=url,
            venue="",
        )

    # eventDatesISO: "2026-03-29" (단일) 또는 "2026-03-29,2026-03-30" (복수 가능)
    dates_raw  = model.get("eventDatesISO", "")
    dates_list = [d.strip() for d in dates_raw.split(",") if d.strip()]
    start_date = _parse_iso_date(dates_list[0])  if dates_list else None
    end_date   = _parse_iso_date(dates_list[-1]) if dates_list else None

    venue = (model.get("place_summ") or model.get("place") or "").strip()[:100]
    name  = (model.get("name") or code).strip()

    return RawTournament(
        source="NEARMINTON",
        external_id=code,
        name=name,
        region_raw="",
        start_date=start_date,
        end_date=end_date,
        original_url=url,
        venue=venue,
    )


def fetch_list(known_ids: set) -> List[RawTournament]:
    session = requests.Session()
    session.headers.update(HEADERS)

    print("  [-] 우동배 목록 페이지 수집 중...")
    try:
        resp = session.get(LIST_URL, timeout=12, verify=False)
        resp.raise_for_status()
    except Exception as e:
        print(f"  [!] 목록 접속 실패: {e}")
        return []

    # /t/{code} 링크 수집 (중복 제거)
    codes = list(dict.fromkeys(CODE_RE.findall(resp.text)))
    new_codes = [c for c in codes if c not in known_ids]
    print(f"  [-] 목록에서 {len(codes)}개 대회 발견, 신규: {len(new_codes)}개")

    tournaments: List[RawTournament] = []
    for code in new_codes:
        t = _fetch_detail(session, code)
        if t:
            tournaments.append(t)
            print(f"  [-] 수집: {code} | {t.start_date} | {t.name[:30]}")
        time.sleep(0.3)

    return tournaments


def collect_tournaments(known_ids: set = None):
    """
    우동배(nearminton.com) 대회 목록 수집.
    신규 /t/{code} 형식 대회만 수집 (구식 숫자 ID 방식 종료).
    """
    known_ids = known_ids or set()
    os.makedirs(RAW_TOURNAMENT_DIR, exist_ok=True)
    print("[*] 우동배(NEARMINTON) 대회 정보 수집 시작 (신규 /t/{code} 방식)...")

    all_tournaments = fetch_list(known_ids)

    if not all_tournaments:
        print("[!] 수집된 신규 우동배 대회가 없습니다.")
        return []

    result = []
    for t in all_tournaments:
        result.append({
            "external_id":  t.external_id,
            "name":         t.name,
            "start_date":   t.start_date.isoformat()  if t.start_date  else None,
            "end_date":     t.end_date.isoformat()    if t.end_date    else None,
            "region_raw":   t.region_raw,
            "venue":        t.venue,
            "external_url": t.original_url,
            "source":       t.source,
        })

    print(f"\n[+] 수집 완료: {len(result)}개 대회")
    if result:
        print(f"    샘플: {result[0]['name']} | {result[0]['start_date']} | {result[0]['venue']}")
    return result


if __name__ == "__main__":
    result = collect_tournaments()
    print(f"\n[Test] 총 {len(result)}개 대회 수집됨.")
    for t in result:
        print(f"  {t['external_id']} | {t['start_date']} | {t['name']}")
