# core/collectors/status_wekkuk.py
"""
status_wekkuk.py
================
위꾹(Wekkuk) 플랫폼에서 특정 대회들의 전적 데이터를 수집합니다.
status_baef.py와 동일한 인터페이스를 따릅니다.

[인터페이스]
    run_wekkuk_stats_hunter(contest_ids: list[str]) -> list[str]

    - contest_ids : Tournament.external_id 문자열 리스트
    - 반환값      : 수집 성공한 external_id 리스트
                   (실패한 항목은 제외 → collect_stats가 마킹 스킵)

[저장 경로]
    data/raw/players/wekkuk_players_{contest_id}.jsonl
    data/raw/winners/wekkuk_winners_{contest_id}.jsonl
"""

import time
import json
import re
from pathlib import Path
from typing import Dict, List, Any, Set, Tuple, Optional

import requests
from bs4 import BeautifulSoup
import urllib3

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# ──────────────────────────────────────────
# 상수
# ──────────────────────────────────────────
BASE         = "https://app2.wekkuk.com"
LIST_API     = f"{BASE}/index.php/v2/contest_badminton/contest_out_search"
PLAYER_HTML  = f"{BASE}/v2/contest_badminton/player/{{bct_id}}"
PLAYER_ACT   = f"{BASE}/v2/contest_badminton/player/act"
WINNER_HTML  = f"{BASE}/v2/contest_badminton/winner_type/{{bct_id}}"

HEADERS_AJAX = {
    "User-Agent": "Mozilla/5.0",
    "X-Requested-With": "XMLHttpRequest",
    "Accept": "application/json, text/javascript, */*; q=0.01",
    "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
}
HEADERS_HTML = {
    "User-Agent": "Mozilla/5.0",
    "Accept": "text/html, */*; q=0.01",
}

NAME_PAT   = re.compile(r"[가-힣]{2,4}")
BLACKLIST  = {"대회", "경기", "종료", "요강", "입상", "참가", "게시", "갤러리",
              "계남", "체육관", "노바스톤", "베르타", "라이더"}
PLACEMENTS = ["우승", "준우승", "3위", "4위"]


# ──────────────────────────────────────────
# 내부 유틸
# ──────────────────────────────────────────
def _s(v: Any) -> str:
    return "" if v is None else str(v).strip()


def _fetch_html(session: requests.Session, url: str, referer: str = "") -> str:
    headers = dict(HEADERS_HTML)
    if referer:
        headers["Referer"] = referer
    try:
        r = session.get(url, headers=headers, timeout=30, verify=False)
        return r.text if r.status_code == 200 else ""
    except Exception:
        return ""


def _parse_categories(html: str) -> List[Tuple[str, str, str]]:
    """선수 목록 페이지에서 (성별, 나이대, 급수) 카테고리 추출"""
    soup = BeautifulSoup(html, "html.parser")
    cats: List[Tuple[str, str, str]] = []
    for a in soup.select(".player-list ul li a[data-tem_sex_play][data-tem_age][data-tem_level]"):
        sex   = (a.get("data-tem_sex_play") or "").strip()
        age   = (a.get("data-tem_age")      or "").strip()
        level = (a.get("data-tem_level")    or "").strip()
        if sex and age and level:
            cats.append((sex, age, level))
    return sorted(set(cats))


def _fetch_players_for_category(
    session: requests.Session,
    bct_id: str,
    sex: str, age: str, level: str,
    referer: str,
) -> List[Dict[str, Any]]:
    """카테고리별 참가자 목록 API 호출"""
    data = {
        "mode": "get_player",
        "bct_id": str(bct_id),
        "tem_sex_play": sex,
        "tem_age": age,
        "tem_level": level,
        "ply_affiliation": "",
        "ply_name": "",
    }
    headers = {**HEADERS_AJAX, "Referer": referer}
    try:
        r = session.post(PLAYER_ACT, headers=headers, data=data, timeout=30, verify=False)
        r.raise_for_status()
        j = r.json()
        if j.get("err") == "Y":
            return []
        return j.get("subItems", []) or []
    except Exception:
        return []


def _normalize_player_rows(
    bct_id: str, title: str,
    sex: str, age: str, level: str,
    subitems: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """API 응답을 통일된 dict 형태로 변환"""
    out = []
    for row in subitems:
        if not row.get("ply1_name"):
            continue
        out.append({
            "contest_id":          bct_id,
            "contest_title":       title,
            "category_sex_play":   sex,
            "category_age_band":   age,
            "category_level":      level,
            "team_id":             row.get("tem_id"),
            "player_name":         row.get("ply1_name"),
            "player_gender":       row.get("ply1_gender"),
            "player_level":        row.get("ply1_level"),
            "affiliation":         row.get("ply1_affiliation"),
            "partner_name":        row.get("ply2_name"),
            "partner_gender":      row.get("ply2_gender"),
            "partner_level":       row.get("ply2_level"),
            "partner_affiliation": row.get("ply2_affiliation"),
            "source": "WEEKUK",
        })
    return out


def _extract_winner_filters(html: str) -> List[Tuple[str, str]]:
    """입상자 페이지의 필터 옵션 (성별/급수) 추출"""
    soup   = BeautifulSoup(html, "html.parser")
    found: Set[Tuple[str, str]] = set()

    for a in soup.find_all("a"):
        href = a.get("href") or ""
        if "winner_type" not in href or "mtb_type" not in href:
            continue
        m1  = re.search(r"mtb_type_sex_play=([^&]+)", href)
        m2  = re.search(r"mtb_type_level=([^&]+)", href)
        sex = (m1.group(1) if m1 else "").strip()
        lvl = (m2.group(1) if m2 else "").strip()
        if sex or lvl:
            found.add((sex, lvl))

    sex_opts: Set[str] = set()
    lvl_opts: Set[str] = set()
    for sel in soup.find_all("select"):
        name = (sel.get("name") or sel.get("id") or "").lower()
        opts = [_s(o.get("value")) for o in sel.find_all("option") if _s(o.get("value"))]
        if "sex" in name or "play" in name:
            sex_opts.update(opts)
        if "level" in name:
            lvl_opts.update(opts)

    if sex_opts and lvl_opts:
        for s in sex_opts:
            for l in lvl_opts:
                found.add((s, l))
    elif sex_opts:
        found.update((s, "") for s in sex_opts)
    elif lvl_opts:
        found.update(("", l) for l in lvl_opts)

    return sorted(found) if found else [("", "")]


def _extract_winners_heuristic(
    bct_id: str, title: str, html: str,
    sex: str, level: str,
) -> List[Dict[str, Any]]:
    """
    위꾹 입상자 페이지는 구조가 대회마다 달라서 휴리스틱으로 파싱.
    텍스트 라인 + 테이블 두 방향으로 시도 후 중복 제거.
    is_heuristic=True 마킹 → 프론트에서 경고 문구 표시 가능.
    """
    if not html:
        return []
    soup  = BeautifulSoup(html, "html.parser")
    lines = [x.strip() for x in soup.get_text("\n").split("\n") if x.strip()]
    out: List[Dict[str, Any]] = []

    # 텍스트 라인 방식
    for i, line in enumerate(lines):
        hit = next((p for p in PLACEMENTS if p in line), "")
        if not hit:
            continue
        window = " ".join(lines[i:i+4])
        names  = [n for n in NAME_PAT.findall(window) if n not in BLACKLIST]
        if not names:
            continue
        out.append({
            "contest_id": bct_id, "contest_title": title,
            "mtb_type_sex_play": sex, "mtb_type_level": level,
            "placement": hit,
            "player1_name": names[0] if len(names) >= 1 else "",
            "player2_name": names[1] if len(names) >= 2 else "",
            "note": "heuristic_text",
            "is_heuristic": True,
            "source": "WEEKUK",
        })

    # 테이블 방식
    for tr in soup.find_all("tr"):
        row_text = tr.get_text(" ", strip=True)
        hit      = next((p for p in PLACEMENTS if p in row_text), "")
        if not hit:
            continue
        names = [n for n in NAME_PAT.findall(row_text) if n not in BLACKLIST]
        if not names:
            continue
        out.append({
            "contest_id": bct_id, "contest_title": title,
            "mtb_type_sex_play": sex, "mtb_type_level": level,
            "placement": hit,
            "player1_name": names[0] if len(names) >= 1 else "",
            "player2_name": names[1] if len(names) >= 2 else "",
            "note": "heuristic_table",
            "is_heuristic": True,
            "source": "WEEKUK",
        })

    # 중복 제거
    uniq = {}
    for r in out:
        k = "|".join([_s(r[f]) for f in ("contest_id", "mtb_type_sex_play", "mtb_type_level", "placement", "player1_name", "player2_name", "note")])
        uniq[k] = r
    return list(uniq.values())


# ──────────────────────────────────────────
# 퍼블릭 인터페이스 (collect_stats.py에서 호출)
# ──────────────────────────────────────────
def run_weekuk_stats_hunter(contest_ids: List[str], sleep: float = 0.2) -> List[str]:
    """
    지정된 대회 ID 목록의 전적 데이터를 수집하고 JSONL로 저장합니다.

    Parameters
    ----------
    contest_ids : Tournament.external_id 문자열 리스트
    sleep       : 요청 간 딜레이 (초)

    Returns
    -------
    success_ids : 수집 성공한 external_id 리스트
                  (collect_stats가 이 목록만 is_stats_fetched=True 마킹)
    """
    import os, sys
    BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

    raw_dir      = Path(BASE_DIR) / "data" / "raw"
    players_dir  = raw_dir / "players"
    winners_dir  = raw_dir / "winners"
    players_dir.mkdir(parents=True, exist_ok=True)
    winners_dir.mkdir(parents=True, exist_ok=True)

    session = requests.Session()
    # 세션 워밍업
    try:
        session.get(f"{BASE}/index.php/v2/contest_badminton/contest_out_find",
                    headers=HEADERS_HTML, timeout=30, verify=False)
    except Exception:
        pass

    success_ids = []

    for bct_id in contest_ids:
        print(f"  [WEEKUK] 수집 시작: {bct_id}")
        player_rows  = 0
        winner_rows  = 0

        try:
            # ── 참가자 수집 ──
            p_url  = PLAYER_HTML.format(bct_id=bct_id)
            p_html = _fetch_html(session, p_url)
            title  = bct_id  # fallback

            if p_html:
                cats = _parse_categories(p_html)
                p_out = players_dir / f"wekkuk_players_{bct_id}.jsonl"

                with open(p_out, "w", encoding="utf-8") as fp:
                    for sex, age, level in cats:
                        subitems = _fetch_players_for_category(
                            session, bct_id, sex, age, level, referer=p_url
                        )
                        rows = _normalize_player_rows(bct_id, title, sex, age, level, subitems)
                        for row in rows:
                            fp.write(json.dumps(row, ensure_ascii=False) + "\n")
                        player_rows += len(rows)
                        time.sleep(sleep)

            # ── 입상자 수집 ──
            w_url  = WINNER_HTML.format(bct_id=bct_id)
            w_html = _fetch_html(session, w_url)
            w_out  = winners_dir / f"wekkuk_winners_{bct_id}.jsonl"

            with open(w_out, "w", encoding="utf-8") as fw:
                if w_html:
                    filters = _extract_winner_filters(w_html)
                    for sex, level in filters:
                        params = f"mtb_type_sex_play={sex}&mtb_type_level={level}&ply_affiliation="
                        url    = f"{w_url}?{params}"
                        html   = _fetch_html(session, url, referer=w_url)
                        rows   = _extract_winners_heuristic(bct_id, title, html, sex, level)
                        for row in rows:
                            fw.write(json.dumps(row, ensure_ascii=False) + "\n")
                        winner_rows += len(rows)
                        time.sleep(min(0.2, sleep))

            print(f"    [v] 완료: 참가자 {player_rows}명 / 입상자 {winner_rows}명")
            success_ids.append(bct_id)

        except Exception as e:
            # 실패한 대회는 success_ids에서 제외 → collect_stats가 마킹 스킵 → 다음 실행에 재시도
            print(f"    [!] 에러 (ID:{bct_id}): {e}")

        time.sleep(sleep)

    return success_ids


# ──────────────────────────────────────────
# 단독 실행 (테스트용)
# ──────────────────────────────────────────
# 구버전 호환 alias
run_wekkuk_stats_hunter = run_weekuk_stats_hunter

if __name__ == "__main__":
    test_ids = ["653", "733"]
    result = run_weekuk_stats_hunter(test_ids)
    print(f"\n[Test] 성공: {result}")
