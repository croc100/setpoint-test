from __future__ import annotations

import time
from typing import List, Set, Tuple

import requests
from bs4 import BeautifulSoup

BASE_URL = "https://app2.wekkuk.com"
PLAYER_HTML_URL = f"{BASE_URL}/v2/contest_badminton/player/{{bct_id}}"
PLAYER_ACT_URL = f"{BASE_URL}/v2/contest_badminton/player/act"

HEADERS_HTML = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Accept": "text/html, */*; q=0.01",
}
HEADERS_AJAX = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "X-Requested-With": "XMLHttpRequest",
    "Accept": "application/json, text/javascript, */*; q=0.01",
    "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
}


def _parse_categories(html: str) -> List[Tuple[str, str, str]]:
    """HTML에서 (sex, age, level) 카테고리 추출"""
    soup = BeautifulSoup(html, "lxml")
    cats: Set[Tuple[str, str, str]] = set()
    for a in soup.select(".player-list ul li a[data-tem_sex_play][data-tem_age][data-tem_level]"):
        sex = (a.get("data-tem_sex_play") or "").strip()
        age = (a.get("data-tem_age") or "").strip()
        lvl = (a.get("data-tem_level") or "").strip()
        if sex and age and lvl:
            cats.add((sex, age, lvl))
    return sorted(cats)


def _fetch_category_players(session: requests.Session, bct_id: str, sex: str, age: str, lvl: str, referer: str) -> List[dict]:
    """특정 종목의 선수 명단을 AJAX로 요청"""
    data = {
        "mode": "get_player",
        "bct_id": bct_id,
        "tem_sex_play": sex,
        "tem_age": age,
        "tem_level": lvl,
        "ply_affiliation": "",
        "ply_name": "",
    }
    headers = {**HEADERS_AJAX, "Referer": referer}
    try:
        res = session.post(PLAYER_ACT_URL, headers=headers, data=data, timeout=30)
        return res.json().get("subItems", []) or []
    except Exception as e:
        print(f"    [!] 위꾹 선수 명단 요청 실패 ({sex}/{age}/{lvl}): {e}")
        return []


def collect_player_stats(tournament: dict) -> List[dict]:
    """
    위꾹 대회 선수 전적 수집.
    참가자 명단만 수집 가능 (매치 스코어 없음 → is_heuristic=True).
    tournament: {external_id, name, start_date, source, external_url, ...}
    반환: List[player_stat_dict]
    """
    bct_id = str(tournament.get("external_id", ""))
    if not bct_id:
        print("  [!] tournament.external_id가 없어 위꾹 선수 수집을 건너뜁니다.")
        return []

    session = requests.Session()
    player_url = PLAYER_HTML_URL.format(bct_id=bct_id)

    print(f"  [-] 위꾹 선수 명단 수집 중 (대회ID: {bct_id})")

    try:
        html = session.get(player_url, headers=HEADERS_HTML, timeout=30).text
    except Exception as e:
        print(f"  [!] 위꾹 선수 페이지 요청 실패: {e}")
        return []

    categories = _parse_categories(html)
    if not categories:
        print("    [경고] 종목 카테고리를 찾을 수 없습니다. 대회가 아직 열리지 않았거나 구조가 다를 수 있습니다.")
        return []

    stats: List[dict] = []

    for sex, age, lvl in categories:
        rows = _fetch_category_players(session, bct_id, sex, age, lvl, referer=player_url)

        for row in rows:
            p1_name = (row.get("ply1_name") or "").strip()
            p1_club = (row.get("ply1_affiliation") or "").strip()
            p2_name = (row.get("ply2_name") or "").strip()

            if p1_name:
                stats.append({
                    "player_name": p1_name,
                    "player_club": p1_club,
                    "external_uid": None,
                    "gender": sex,
                    "category_age_band": age,
                    "category_level": lvl,
                    "rank": None,
                    "final_status": None,
                    "win_count": 0,
                    "loss_count": 0,
                    "gain_point": 0,
                    "is_heuristic": True,  # 매치 결과 없이 참가 사실만 확인
                    "matches": [],
                })

        time.sleep(0.1)

    print(f"    → {len(stats)}명 수집 완료")
    return stats
