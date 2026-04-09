import argparse
import json
import os
import re
import time
from pathlib import Path
from typing import Dict, List, Any, Iterable, Tuple, Set

import requests
from bs4 import BeautifulSoup

# ==========================================
# [1] API 엔드포인트 및 헤더 설정
# ==========================================
BASE = "https://app2.wekkuk.com"
LIST_API = f"{BASE}/index.php/v2/contest_badminton/contest_out_search"
PLAYER_HTML = f"{BASE}/v2/contest_badminton/player/{{bct_id}}"
PLAYER_ACT = f"{BASE}/v2/contest_badminton/player/act"
WINNER_HTML = f"{BASE}/v2/contest_badminton/winner_type/{{bct_id}}"

HEADERS_AJAX = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "X-Requested-With": "XMLHttpRequest",
    "Accept": "application/json, text/javascript, */*; q=0.01",
    "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
}
HEADERS_HTML = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Accept": "text/html, */*; q=0.01",
}

# ==========================================
# [2] 유틸리티 함수
# ==========================================
def _s(v: Any) -> str:
    return str(v).strip() if v is not None else ""

def _mkdir_parent(path_str: str) -> None:
    p = Path(path_str).expanduser()
    p.parent.mkdir(parents=True, exist_ok=True)

# ==========================================
# [3] 데이터 수집 핵심 로직
# ==========================================
def iter_contests(session: requests.Session, start_page: int = 1) -> Iterable[Dict[str, Any]]:
    """API를 통해 전체 대회 목록을 최신순으로 가져옵니다."""
    page = start_page
    while True:
        data = {"mode": "contest_out_search", "type": "find", "sf": "", "sw": "", "page": str(page)}
        r = session.post(LIST_API, headers=HEADERS_AJAX, data=data, timeout=30)
        r.raise_for_status()
        j = r.json()

        if j.get("err") == "Y":
            break

        for it in j.get("items", []):
            yield it

        if j.get("is_end") is True:
            break

        page += 1
        time.sleep(0.5) # 서버 보호를 위한 딜레이

def parse_categories(html: str) -> List[Tuple[str, str, str]]:
    """HTML에서 참가 종목(연령, 급수, 성별) 카테고리를 lxml로 초고속 파싱합니다."""
    soup = BeautifulSoup(html, "lxml") # [SE Fix] lxml 적용 (CPU 최적화)
    cats: Set[Tuple[str, str, str]] = set()
    for a in soup.select(".player-list ul li a[data-tem_sex_play][data-tem_age][data-tem_level]"):
        sex = _s(a.get("data-tem_sex_play"))
        age = _s(a.get("data-tem_age"))
        lvl = _s(a.get("data-tem_level"))
        if sex and age and lvl:
            cats.add((sex, age, lvl))
    return sorted(cats)

def fetch_players(session: requests.Session, bct_id: str, sex: str, age: str, lvl: str, referer: str) -> List[Dict[str, Any]]:
    """특정 종목의 선수 명단을 API로 요청합니다."""
    data = {
        "mode": "get_player", "bct_id": str(bct_id),
        "tem_sex_play": sex, "tem_age": age, "tem_level": lvl,
        "ply_affiliation": "", "ply_name": "",
    }
    headers = dict(HEADERS_AJAX)
    headers["Referer"] = referer
    r = session.post(PLAYER_ACT, headers=headers, data=data, timeout=30)
    return r.json().get("subItems", []) or []

# ==========================================
# [4] 메인 오케스트레이터 (테스트 실행부)
# ==========================================
def main():
    parser = argparse.ArgumentParser(description="위꾹 선수 데이터 수집 테스트 스크립트")
    parser.add_argument("--out", type=str, default="data/test_wekkuk_players.jsonl", help="출력 파일 경로")
    parser.add_argument("--max", type=int, default=3, help="테스트할 최대 대회 수 (기본 3개)")
    parser.add_argument("--force-recent", type=int, default=2, help="항상 덮어쓸 최신 대회 수 (조기 캐싱 방지)")
    args = parser.parse_args()

    out_file = args.out
    _mkdir_parent(out_file)

    # [SE Architecture] 중단점 기억 로직 (기존 수집된 bct_id 스캔)
    completed_bct_ids = set()
    if os.path.exists(out_file):
        with open(out_file, "r", encoding="utf-8") as f:
            for line in f:
                try:
                    completed_bct_ids.add(str(json.loads(line).get("contest_id")))
                except json.JSONDecodeError:
                    pass
    
    print("="*60)
    print(f"[*] 위꾹 크롤링 테스트 파이프라인 가동")
    print(f"[*] 기존 수집 캐시: {len(completed_bct_ids)}개 대회 기억 중")
    print("="*60)

    session = requests.Session()
    
    # [SE Architecture] 덮어쓰기가 아닌 이어쓰기(Append) 모드로 파일 오픈
    with open(out_file, "a", encoding="utf-8") as f_out:
        contests_processed = 0
        
        for idx, contest in enumerate(iter_contests(session)):
            bct_id = _s(contest.get("idx"))
            title = _s(contest.get("title"))
            
            if not bct_id: continue

            # [SE Logic] 조기 캐싱 방지: 
            # 최상단(최신) N개의 대회는 무조건 다시 긁고, 그 외 과거 대회는 파일에 있으면 스킵
            is_recent_force = idx < args.force_recent
            
            if not is_recent_force and bct_id in completed_bct_ids:
                print(f"  [-] 스킵 (캐시됨): {title} ({bct_id})")
                continue

            print(f"\n[+] 수집 시작: {title} ({bct_id}) - 강제수집 여부: {is_recent_force}")
            
            player_url = PLAYER_HTML.format(bct_id=bct_id)
            html = session.get(player_url, headers=HEADERS_HTML, timeout=30).text
            cats = parse_categories(html)
            
            if not cats:
                print("    -> [경고] 카테고리(종목)를 찾을 수 없습니다. 대회가 열리지 않았거나 구조가 다릅니다.")
                continue

            players_count = 0
            for sex, age, lvl in cats:
                subitems = fetch_players(session, bct_id, sex, age, lvl, referer=player_url)
                
                for row in subitems:
                    if not row.get("ply1_name"): continue
                    
                    # 데이터 정규화
                    normalized_data = {
                        "contest_id": bct_id,
                        "contest_title": title,
                        "category_sex_play": sex,
                        "category_age_band": age,
                        "category_level": lvl,
                        "player1_name": row.get("ply1_name"),
                        "player1_gender": row.get("ply1_gender"),
                        "player1_affiliation": row.get("ply1_affiliation"),
                        "player2_name": row.get("ply2_name"),
                        "source": "WEEKUK"
                    }
                    # 파일에 즉시 한 줄 쓰기
                    f_out.write(json.dumps(normalized_data, ensure_ascii=False) + "\n")
                    players_count += 1
                
                time.sleep(0.1) # 종목 긁을 때마다 짧은 딜레이

            print(f"    -> [완료] {players_count}명의 선수 데이터 적재 완료")
            
            contests_processed += 1
            if args.max > 0 and contests_processed >= args.max:
                print("\n[*] 설정된 최대 테스트 개수(--max)에 도달하여 종료합니다.")
                break

    print("="*60)
    print(f"[*] 테스트 종료. 결과 파일: {out_file}")
    print("="*60)

if __name__ == "__main__":
    main()