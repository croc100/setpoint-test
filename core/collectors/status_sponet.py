# core/collectors/status_sponet.py
"""
status_sponet.py
================
SPONET 플랫폼에서 특정 대회들의 전적 데이터를 수집합니다.
status_wekkuk.py와 동일한 인터페이스를 따릅니다.

[인터페이스]
    run_sponet_stats_hunter(contest_ids: list[str]) -> list[str]

    - contest_ids : Tournament.external_id 문자열 리스트 (예: "TM_20260215151506")
    - 반환값      : 수집 성공한 external_id 리스트

[API 흐름 (Vercel 프록시 경유)]
    1. event-list      → 종목(이벤트) 목록 수집
    2. entry-list      → 각 종목 참가자 수집 → players JSONL
    3. draw-list       → 드로우(예선조/결승) 목록 수집
    4. match-list      → 결승 드로우 경기 수집 → winners JSONL

[저장 경로]
    data/raw/players/sponet_players_{tournament_id}.jsonl
    data/raw/winners/sponet_winners_{tournament_id}.jsonl
"""

import os
import json
import time
from pathlib import Path
from typing import List, Dict, Any, Tuple

import requests

# ──────────────────────────────────────────
# 상수
# ──────────────────────────────────────────
PROXY_BASE = "https://sponet-proxy.vercel.app/api"
HEADERS = {
    "Content-Type": "application/json",
    "Accept": "application/json",
}

# 결승 드로우 판별 키워드
FINAL_KEYWORDS = ("결승", "본선", "Final", "파이널")


# ──────────────────────────────────────────
# 내부 API 헬퍼
# ──────────────────────────────────────────
def _post(endpoint: str, body: dict, retries: int = 2) -> dict:
    url = f"{PROXY_BASE}/{endpoint}"
    for attempt in range(retries + 1):
        try:
            r = requests.post(url, json=body, headers=HEADERS, timeout=30)
            if r.status_code == 200:
                return r.json()
            return {}
        except Exception:
            if attempt < retries:
                time.sleep(1)
    return {}


def _get_events(tournament_id: str) -> List[Dict]:
    resp = _post("event-list", {
        "p_tournament_id": tournament_id,
        "p_event_id": "",
        "p_game_type": "",
        "p_gender": "",
        "p_game_level": "",
    })
    return resp.get("data_list", []) or []


def _get_entries(tournament_id: str, event_id: str) -> List[Dict]:
    resp = _post("entry-list", {
        "p_tournament_id": tournament_id,
        "p_event_id": event_id,
        "p_gender": "",
        "p_game_type": "",
        "p_game_level": "",
    })
    return resp.get("data_list", []) or []


def _get_draws(tournament_id: str, event_id: str) -> List[Dict]:
    resp = _post("draw-list", {
        "p_tournament_id": tournament_id,
        "p_event_id": event_id,
    })
    return resp.get("data_list", []) or []


def _get_matches(tournament_id: str, event_id: str, draw_id: str) -> List[Dict]:
    resp = _post("match-list", {
        "p_tournament_id": tournament_id,
        "p_event_id": event_id,
        "p_draw_id": draw_id,
    })
    return resp.get("matchRBInfo", []) or []


# ──────────────────────────────────────────
# 내부 유틸
# ──────────────────────────────────────────
def _split_pair(player_str: str) -> Tuple[str, str]:
    """'이름1 / 이름2' → (이름1, 이름2). 단식이면 (이름, '')"""
    if "/" in player_str:
        parts = [p.strip() for p in player_str.split("/", 1)]
        return parts[0], parts[1]
    return player_str.strip(), ""


def _is_final_draw(draw: Dict) -> bool:
    nm = (draw.get("DRAW_NM") or "").strip()
    return any(kw in nm for kw in FINAL_KEYWORDS)


def _extract_placements(
    matches: List[Dict],
    event_id: str,
    event_nm: str,
    contest_id: str,
    contest_title: str,
) -> List[Dict]:
    """
    완료된 경기(MATCH_STS='Y') 중 결승전과 3·4위전을 찾아 입상자 추출.

    결승전 판별: NEXTPLAN_NO 가 없는(null/빈) 완료 경기 = 더 이상 진출할 경기 없음
    3·4위전: 역시 NEXTPLAN_NO 없는 완료 경기 중 결승전이 아닌 것
    """
    if not matches:
        return []

    # 완료 + 양팀 이름 모두 있는 경기만
    finished = [
        m for m in matches
        if m.get("MATCH_STS") == "Y"
        and (m.get("T1_PLAYER") or "").strip()
        and (m.get("T2_PLAYER") or "").strip()
        and str(m.get("WIN") or "") in ("1", "2")
    ]
    if not finished:
        return []

    # NEXTPLAN_NO 가 없거나 비어 있는 경기 = 더 이상 올라갈 대진 없음 (결승 or 3위전)
    terminal_matches = [
        m for m in finished
        if not str(m.get("NEXTPLAN_NO") or "").strip()
    ]

    # NEXTPLAN_NO 가 있는 경기들의 번호 집합 (semi-final 등)
    non_terminal = [
        m for m in finished
        if str(m.get("NEXTPLAN_NO") or "").strip()
    ]

    # terminal_matches 가 없으면 SEQ 기준 최후 경기를 결승으로 간주
    if not terminal_matches:
        terminal_matches = [max(finished, key=lambda m: int(float(m.get("SEQ") or 0)))]

    results: List[Dict] = []

    def _make_rows(match: Dict, gold_placement: str, silver_placement: str) -> List[Dict]:
        win_flag = str(match.get("WIN") or "")
        t1_str   = (match.get("T1_PLAYER") or "").strip()
        t1_club  = (match.get("T1CLUB") or "").strip()
        t2_str   = (match.get("T2_PLAYER") or "").strip()
        t2_club  = (match.get("T2CLUB") or "").strip()

        winner_str  = t1_str  if win_flag == "1" else t2_str
        winner_club = t1_club if win_flag == "1" else t2_club
        loser_str   = t2_str  if win_flag == "1" else t1_str
        loser_club  = t2_club if win_flag == "1" else t1_club

        w1, w2 = _split_pair(winner_str)
        l1, l2 = _split_pair(loser_str)

        rows = []
        if w1:
            rows.append({
                "contest_id": contest_id, "contest_title": contest_title,
                "event_id": event_id, "event_nm": event_nm,
                "placement": gold_placement,
                "player1_name": w1, "player2_name": w2,
                "club": winner_club, "source": "SPONET",
            })
        if l1:
            rows.append({
                "contest_id": contest_id, "contest_title": contest_title,
                "event_id": event_id, "event_nm": event_nm,
                "placement": silver_placement,
                "player1_name": l1, "player2_name": l2,
                "club": loser_club, "source": "SPONET",
            })
        return rows

    if len(terminal_matches) == 1:
        # 결승전 1개만 있음
        results += _make_rows(terminal_matches[0], "우승", "준우승")

    elif len(terminal_matches) >= 2:
        # SEQ가 높은 게 결승, 낮은 게 3·4위전
        sorted_t = sorted(terminal_matches, key=lambda m: int(float(m.get("SEQ") or 0)), reverse=True)
        results += _make_rows(sorted_t[0], "우승", "준우승")
        results += _make_rows(sorted_t[1], "3위", "4위")

    return results


# ──────────────────────────────────────────
# 퍼블릭 인터페이스
# ──────────────────────────────────────────
def run_sponet_stats_hunter(contest_ids: List[str], sleep: float = 0.3) -> List[str]:
    """
    지정된 SPONET 대회 ID 목록의 전적 데이터를 수집하고 JSONL로 저장합니다.

    Parameters
    ----------
    contest_ids : Tournament.external_id 문자열 리스트
    sleep       : 요청 간 딜레이 (초)

    Returns
    -------
    success_ids : 수집 성공한 external_id 리스트
    """
    BASE_DIR    = Path(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
    players_dir = BASE_DIR / "data" / "raw" / "players"
    winners_dir = BASE_DIR / "data" / "raw" / "winners"
    players_dir.mkdir(parents=True, exist_ok=True)
    winners_dir.mkdir(parents=True, exist_ok=True)

    success_ids: List[str] = []

    for tid in contest_ids:
        print(f"  [SPONET] 수집 시작: {tid}")
        player_rows = 0
        winner_rows = 0

        try:
            events = _get_events(tid)

            # 이벤트 없음 = 아직 대진 미등록 대회. 완료 처리하지 않고 스킵.
            if not events:
                print(f"    [-] 이벤트 없음, 스킵: {tid}")
                continue

            # contest_title: event-list에 TOURNAMENT_NM 없음 → tid 사용
            # load_stats._load_sponet 에서 DB의 기존 name을 덮어쓰지 않도록 처리됨
            contest_title = tid

            p_out = players_dir / f"sponet_players_{tid}.jsonl"
            w_out = winners_dir  / f"sponet_winners_{tid}.jsonl"

            with open(p_out, "w", encoding="utf-8") as pf, \
                 open(w_out, "w", encoding="utf-8") as wf:

                for event in events:
                    event_id  = str(event.get("EVENT_ID") or "").strip()
                    event_nm  = str(event.get("EVENT_NM") or "").strip()
                    age_band  = str(event.get("AGE")      or "").strip()
                    level     = str(event.get("LEVEL")    or "").strip()
                    gender    = str(event.get("GENDER")   or "").strip()
                    game_type = str(event.get("GAME_TYPE") or "").strip()

                    if not event_id:
                        continue

                    # ── 참가자 수집 ──
                    entries = _get_entries(tid, event_id)
                    for entry in entries:
                        p1 = (entry.get("PLAYER_NM1") or "").strip()
                        c1 = (entry.get("CLUB_NM1")   or "").strip()
                        p2 = (entry.get("PLAYER_NM2") or "").strip()
                        c2 = (entry.get("CLUB_NM2")   or "").strip()
                        if not p1:
                            continue
                        pf.write(json.dumps({
                            "contest_id":       tid,
                            "contest_title":    contest_title,
                            "event_id":         event_id,
                            "event_nm":         event_nm,
                            "category_age_band": age_band,
                            "category_level":   level,
                            "gender":           gender,
                            "game_type":        game_type,
                            "player_name":      p1,
                            "club":             c1,
                            "partner_name":     p2,
                            "partner_club":     c2,
                            "source":           "SPONET",
                        }, ensure_ascii=False) + "\n")
                        player_rows += 1
                    time.sleep(sleep)

                    # ── 입상자 수집 (결승 드로우) ──
                    draws = _get_draws(tid, event_id)
                    if not draws:
                        continue

                    # 결승 키워드 포함 드로우 우선, 없으면 마지막 드로우
                    final_draws = [d for d in draws if _is_final_draw(d)]
                    target_draws = final_draws if final_draws else [draws[-1]]

                    for draw in target_draws:
                        draw_id = str(draw.get("DRAW_ID") or "").strip()
                        if not draw_id:
                            continue
                        matches    = _get_matches(tid, event_id, draw_id)
                        placements = _extract_placements(
                            matches, event_id, event_nm, tid, contest_title
                        )
                        for row in placements:
                            wf.write(json.dumps(row, ensure_ascii=False) + "\n")
                            winner_rows += 1
                        time.sleep(sleep)

            print(f"    [v] 완료: 참가자 {player_rows}명 / 입상자 {winner_rows}명")
            success_ids.append(tid)

        except Exception as e:
            print(f"    [!] 에러 (ID:{tid}): {e}")

        time.sleep(sleep)

    return success_ids


# ──────────────────────────────────────────
# 단독 실행 (테스트용)
# ──────────────────────────────────────────
if __name__ == "__main__":
    test_ids = ["TM_20260215151506"]
    result = run_sponet_stats_hunter(test_ids)
    print(f"\n[Test] 성공: {result}")
