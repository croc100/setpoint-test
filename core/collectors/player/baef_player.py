from __future__ import annotations

import os
import re
import time
from typing import Dict, List, Optional, Tuple

import requests
import urllib3

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

BASE_API = "https://real.badmintonfriends.co.kr"


def _get_headers(token: str) -> dict:
    return {
        "accept-encoding": "gzip",
        "content-type": "application/json",
        "cookie": f"BADDY_TOKEN={token}",
        "host": "real.badmintonfriends.co.kr",
        "user-agent": "Dart/3.6 (dart:io)",
    }


def _get_token() -> Optional[str]:
    token = os.environ.get("BAEF_TOKEN", "").strip()
    if not token:
        print("  [!] BAEF_TOKEN 환경변수가 설정되지 않았습니다. 선수 전적 수집을 건너뜁니다.")
    return token or None


def _parse_category(category_full: str) -> Tuple[str, str, str]:
    """'남성 D조 30대' → ('남성', '30대', 'D조')"""
    gender = next((g for g in ["남성", "여성", "혼합"] if g in category_full), "")
    age_band = next((a for a in ["10대", "20대", "30대", "40대", "50대", "60대", "70대", "오픈"] if a in category_full), "")
    level = next((l for l in ["S조", "A조", "B조", "C조", "D조", "E조"] if l in category_full), "")
    return gender, age_band, level


def _rank_to_final_status(rank_text: str) -> str:
    if not rank_text:
        return ""
    if rank_text in ("우승",):
        return "우승"
    if rank_text in ("준우승", "2위"):
        return "준우승"
    if rank_text in ("3위", "4위", "공동3위"):
        return "3위"
    if "강" in rank_text:
        return "본선진출"
    return "예선탈락"


def _extract_pks(detail_result: dict) -> Tuple[str, List[str]]:
    """대회 상세 정보에서 CONCAT_PK(참가자 조회용)와 AGE_PK 리스트(순위 조회용) 추출"""
    pks: List[str] = []
    for gubun in detail_result.get("PROGRESS_GUBUN_LIST", []):
        for grade in gubun.get("GRADE_LIST", []):
            pk = grade.get("AGE_PK")
            if pk:
                pks.append(str(pk))
    concat_pk = ",".join(pks)
    return concat_pk, list(dict.fromkeys(pks))  # 순서 보존 중복제거


def _fetch_participants(session: requests.Session, contest_id: str, concat_pk: str, headers: dict) -> List[dict]:
    """전체 참가자 명단 수집 (페이징)"""
    url = f"{BASE_API}/comp/apply/team/list/{contest_id}"
    participants: List[dict] = []
    offset = 0

    while True:
        try:
            res = session.post(
                url,
                params={"offsetNo": offset, "orderBy": "desc"},
                json={"CONCAT_PK": concat_pk},
                headers=headers,
                timeout=15,
            ).json()
            teams = res.get("result", {}).get("APPLY_INFO_LIST", [])
            if not teams:
                break

            for team in teams:
                details = team.get("TEAM_DETAIL_LIST", [])

                def _name(p: dict) -> str:
                    return p.get("NM") or p.get("NAME") or p.get("MBER_NM") or ""

                def _club(p: dict) -> str:
                    return p.get("GROUP_NAME") or p.get("CLB_NM") or ""

                p1 = details[0] if len(details) > 0 else {}
                p2 = details[1] if len(details) > 1 else {}

                p1_name = _name(p1) or team.get("PLAYER1_NAME") or team.get("MBER_NM") or ""
                p1_club = _club(p1)
                p2_name = _name(p2) or team.get("PLAYER2_NAME") or team.get("PARTNER_NM") or ""
                p2_club = _club(p2)
                category_full = team.get("GRADE_TEXT") or team.get("GRADE_AGE_TEXT") or ""

                if p1_name:
                    participants.append({"name": p1_name, "club": p1_club, "category_full": category_full})
                if p2_name:
                    participants.append({"name": p2_name, "club": p2_club, "category_full": category_full})

            offset += len(teams)
            time.sleep(0.3)
        except Exception as e:
            print(f"    [!] 참가자 명단 수집 오류 (offset={offset}): {e}")
            break

    return participants


def _fetch_final_ranks(session: requests.Session, contest_id: str, age_pks: List[str], headers: dict) -> Dict[Tuple[str, str], str]:
    """최종 순위(우승/준우승/3위/8강 등) 수집. {(player_name, category_full): rank_text}"""
    rank_map: Dict[Tuple[str, str], str] = {}
    url = f"{BASE_API}/comp/intime/apply/match/result/{contest_id}/team"

    for age_pk in age_pks:
        try:
            res = session.get(url, headers=headers, params={"agePk": age_pk}, timeout=10).json()
            for match_group in res.get("result", {}).get("MATCH_RANK_LIST", []):
                category = match_group.get("GUBUN_FULL_TEXT", "")
                for item in match_group.get("RANK_LIST", []):
                    rank_text = item.get("WIN_TYPE_TEXT", "")
                    det = item.get("TEAM_DETAIL_LIST", [])
                    for p in det:
                        name = p.get("NM") or p.get("NAME") or ""
                        if name:
                            rank_map[(name, category)] = rank_text
            time.sleep(0.2)
        except Exception as e:
            print(f"    [!] 순위 수집 오류 (age_pk={age_pk}): {e}")

    return rank_map


def collect_player_stats(tournament: dict) -> List[dict]:
    """
    BAEF 대회 선수 전적 수집.
    tournament: {external_id, name, start_date, source, external_url, ...}
    환경변수 BAEF_TOKEN 필요.
    반환: List[player_stat_dict]
    """
    token = _get_token()
    if not token:
        return []

    contest_id = str(tournament.get("external_id", ""))
    if not contest_id:
        print("  [!] tournament.external_id가 없어 BAEF 선수 수집을 건너뜁니다.")
        return []

    headers = _get_headers(token)
    session = requests.Session()

    # 1. 대회 상세 → PKs 추출
    try:
        detail_url = f"{BASE_API}/comp/v2/detail/{contest_id}"
        res = session.get(detail_url, headers=headers, timeout=10).json()
        if res.get("resCode") != "001" or not res.get("result"):
            print(f"  [!] BAEF 대회 {contest_id} 상세 조회 실패 (resCode={res.get('resCode')})")
            return []
        detail = res["result"]
    except Exception as e:
        print(f"  [!] BAEF 대회 상세 요청 실패: {e}")
        return []

    concat_pk, age_pks = _extract_pks(detail)
    if not concat_pk:
        print(f"  [-] 대회 {contest_id}: 종목 PK 없음 (접수 전이거나 결과 없음)")
        return []

    print(f"  [-] 참가자 명단 수집 중 (대회ID: {contest_id}, 종목 수: {len(age_pks)})")

    # 2. 참가자 명단
    participants = _fetch_participants(session, contest_id, concat_pk, headers)
    print(f"    → 참가자 {len(participants)}명")

    # 3. 최종 순위
    rank_map = _fetch_final_ranks(session, contest_id, age_pks, headers)
    print(f"    → 순위 데이터 {len(rank_map)}명")

    # 4. 조합 → 표준 포맷
    stats: List[dict] = []
    seen: set = set()  # (name, category_full) 중복 방지

    for p in participants:
        name = p["name"].strip()
        club = p["club"].strip()
        category_full = p["category_full"].strip()
        key = (name, category_full)

        if key in seen:
            continue
        seen.add(key)

        gender, age_band, level = _parse_category(category_full)
        rank_text = rank_map.get(key, "")
        final_status = _rank_to_final_status(rank_text)

        stats.append({
            "player_name": name,
            "player_club": club,
            "external_uid": None,
            "gender": gender,
            "category_age_band": age_band,
            "category_level": level,
            "rank": rank_text or None,
            "final_status": final_status or None,
            "win_count": 0,
            "loss_count": 0,
            "gain_point": 0,
            "is_heuristic": False,
            "matches": [],
        })

    print(f"    → 최종 {len(stats)}명 통합 완료")
    return stats
