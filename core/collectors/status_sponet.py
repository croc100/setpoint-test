# core/collectors/status_sponet.py
"""
status_sponet.py
================
SPONET 플랫폼에서 특정 대회들의 전적 데이터를 수집합니다.

[변경사항]
    ThreadPoolExecutor 도입으로 이벤트·대회 단위 병렬 수집.
    Vercel 프록시 부하 감안 → max_workers=3 (보수적)

[저장 경로]
    data/raw/players/sponet_players_{tournament_id}.jsonl
    data/raw/winners/sponet_winners_{tournament_id}.jsonl
"""

import os
import json
import time
from pathlib import Path
from typing import List, Dict, Any, Tuple
from concurrent.futures import ThreadPoolExecutor, as_completed

import requests

# ──────────────────────────────────────────
# 상수
# ──────────────────────────────────────────
PROXY_BASE = "https://sponet-proxy.vercel.app/api"
HEADERS = {
    "Content-Type": "application/json",
    "Accept": "application/json",
}

FINAL_KEYWORDS = ("결승", "본선", "Final", "파이널")

# 동시 요청 수 (Vercel 프록시 부하 고려)
EVENT_WORKERS      = 3   # 이벤트 단위 병렬 수
TOURNAMENT_WORKERS = 3   # 대회 단위 병렬 수


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
    if not matches:
        return []

    finished = [
        m for m in matches
        if m.get("MATCH_STS") == "Y"
        and (m.get("T1_PLAYER") or "").strip()
        and (m.get("T2_PLAYER") or "").strip()
        and str(m.get("WIN") or "") in ("1", "2")
    ]
    if not finished:
        return []

    terminal_matches = [
        m for m in finished
        if not str(m.get("NEXTPLAN_NO") or "").strip()
    ]

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
        results += _make_rows(terminal_matches[0], "우승", "준우승")
    elif len(terminal_matches) >= 2:
        sorted_t = sorted(terminal_matches, key=lambda m: int(float(m.get("SEQ") or 0)), reverse=True)
        results += _make_rows(sorted_t[0], "우승", "준우승")
        results += _make_rows(sorted_t[1], "3위", "4위")

    return results


# ──────────────────────────────────────────
# 이벤트 단위 처리 (병렬 실행 단위)
# ──────────────────────────────────────────
def _process_event(tid: str, event: Dict, contest_title: str, sleep: float) -> Tuple[List[Dict], List[Dict]]:
    """
    단일 이벤트의 참가자·입상자를 수집해 리스트로 반환.
    파일 I/O 없음 → 스레드 안전.
    """
    event_id  = str(event.get("EVENT_ID") or "").strip()
    event_nm  = str(event.get("EVENT_NM") or "").strip()
    age_band  = str(event.get("AGE")      or "").strip()
    level     = str(event.get("LEVEL")    or "").strip()
    gender    = str(event.get("GENDER")   or "").strip()
    game_type = str(event.get("GAME_TYPE") or "").strip()

    if not event_id:
        return [], []

    player_rows: List[Dict] = []
    winner_rows: List[Dict] = []

    # ── 참가자 ──
    entries = _get_entries(tid, event_id)
    for entry in entries:
        p1 = (entry.get("PLAYER_NM1") or "").strip()
        c1 = (entry.get("CLUB_NM1")   or "").strip()
        p2 = (entry.get("PLAYER_NM2") or "").strip()
        c2 = (entry.get("CLUB_NM2")   or "").strip()
        if not p1:
            continue
        player_rows.append({
            "contest_id":        tid,
            "contest_title":     contest_title,
            "event_id":          event_id,
            "event_nm":          event_nm,
            "category_age_band": age_band,
            "category_level":    level,
            "gender":            gender,
            "game_type":         game_type,
            "player_name":       p1,
            "club":              c1,
            "partner_name":      p2,
            "partner_club":      c2,
            "source":            "SPONET",
        })

    # ── 입상자 ──
    draws = _get_draws(tid, event_id)
    if draws:
        final_draws  = [d for d in draws if _is_final_draw(d)]
        target_draws = final_draws if final_draws else [draws[-1]]
        for draw in target_draws:
            draw_id = str(draw.get("DRAW_ID") or "").strip()
            if not draw_id:
                continue
            matches    = _get_matches(tid, event_id, draw_id)
            placements = _extract_placements(matches, event_id, event_nm, tid, contest_title)
            winner_rows.extend(placements)

    return player_rows, winner_rows


# ──────────────────────────────────────────
# 대회 단위 처리 (병렬 실행 단위)
# ──────────────────────────────────────────
def _process_tournament(
    tid: str,
    players_dir: Path,
    winners_dir: Path,
    sleep: float,
) -> bool:
    """
    단일 대회의 전적을 수집하고 JSONL에 저장.
    반환값: True(성공) / False(실패·스킵)
    """
    print(f"  [SPONET] 수집 시작: {tid}")

    try:
        events = _get_events(tid)
        if not events:
            print(f"    [-] 이벤트 없음, 스킵: {tid}")
            return False

        contest_title = tid
        all_players: List[Dict] = []
        all_winners: List[Dict] = []

        # ── 이벤트 병렬 처리 ──
        with ThreadPoolExecutor(max_workers=EVENT_WORKERS) as ex:
            futures = {
                ex.submit(_process_event, tid, event, contest_title, sleep): event
                for event in events
            }
            for future in as_completed(futures):
                try:
                    p_rows, w_rows = future.result()
                    all_players.extend(p_rows)
                    all_winners.extend(w_rows)
                except Exception as e:
                    print(f"    [!] 이벤트 처리 오류: {e}")

        # ── JSONL 저장 ──
        p_out = players_dir / f"sponet_players_{tid}.jsonl"
        w_out = winners_dir / f"sponet_winners_{tid}.jsonl"

        with open(p_out, "w", encoding="utf-8") as pf:
            for row in all_players:
                pf.write(json.dumps(row, ensure_ascii=False) + "\n")

        with open(w_out, "w", encoding="utf-8") as wf:
            for row in all_winners:
                wf.write(json.dumps(row, ensure_ascii=False) + "\n")

        print(f"    [v] 완료: 참가자 {len(all_players)}명 / 입상자 {len(all_winners)}명")
        return True

    except Exception as e:
        print(f"    [!] 에러 (ID:{tid}): {e}")
        return False


# ──────────────────────────────────────────
# 퍼블릭 인터페이스
# ──────────────────────────────────────────
def run_sponet_stats_hunter(contest_ids: List[str], sleep: float = 0.3) -> List[str]:
    """
    지정된 SPONET 대회 ID 목록의 전적 데이터를 병렬 수집합니다.

    Parameters
    ----------
    contest_ids : Tournament.external_id 문자열 리스트
    sleep       : 개별 API 요청 간 딜레이 (초) — 현재 미사용(병렬화로 대체)

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

    # ── 대회 병렬 처리 ──
    with ThreadPoolExecutor(max_workers=TOURNAMENT_WORKERS) as ex:
        futures = {
            ex.submit(_process_tournament, tid, players_dir, winners_dir, sleep): tid
            for tid in contest_ids
        }
        for future in as_completed(futures):
            tid = futures[future]
            try:
                if future.result():
                    success_ids.append(tid)
            except Exception as e:
                print(f"  [!] 대회 처리 실패 (ID:{tid}): {e}")

    return success_ids


# ──────────────────────────────────────────
# 단독 실행 (테스트용)
# ──────────────────────────────────────────
if __name__ == "__main__":
    test_ids = ["TM_20260215151506"]
    result = run_sponet_stats_hunter(test_ids)
    print(f"\n[Test] 성공: {result}")
