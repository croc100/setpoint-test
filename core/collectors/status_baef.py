"""
status_baef.py
==============
BAEF(배드민턴프렌즈) 대회 전적 수집기

ID 체계 이중화 주의:
  - DB external_id  : oopy.io(Notion) UUID  예) "2807e695-4f78-..."
  - BAEF 백엔드 API : 숫자형 contest_id     예) "215"

  대회 공지 페이지(oopy.io)를 파싱해서 숫자 ID를 먼저 찾은 뒤
  API 호출에 사용한다. JSONL 파일명은 UUID로 저장하여 load_stats
  와의 매핑이 끊기지 않도록 한다.
"""

import os
import re
import sys
import time
import json
import requests
import urllib3
from pathlib import Path
from typing import Optional

from bs4 import BeautifulSoup
from dotenv import load_dotenv

# ── 환경 설정 ──────────────────────────────────────────────
BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if BASE_DIR not in sys.path:
    sys.path.append(BASE_DIR)

env_path = os.path.join(BASE_DIR, ".env")
load_dotenv(env_path)

BADDY_TOKEN = os.environ.get("BADDY_TOKEN", "")
if not BADDY_TOKEN:
    print(f"[!] 경고: BADDY_TOKEN을 찾을 수 없음 (확인 경로: {env_path})")
else:
    print(f"[*] 환경 변수 로드 성공 (Token: {BADDY_TOKEN[:10]}...)")

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# BAEF 백엔드 API 헤더
API_HEADERS = {
    "accept-encoding": "gzip",
    "content-type": "application/json",
    "cookie": f"BADDY_TOKEN={BADDY_TOKEN}",
    "host": "real.badmintonfriends.co.kr",
    "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/120.0.0.0 Safari/537.36",
}

# oopy.io 페이지 크롤링 헤더 (별도)
WEB_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/129.0.0.0 Safari/537.36",
    "Accept-Language": "ko-KR,ko;q=0.9",
    "Referer": "https://www.badmintonfriends.co.kr/",
}

# ── 데이터 저장소 ───────────────────────────────────────────
RAW_DIR    = Path(BASE_DIR) / "data" / "raw"
PLAYER_DIR = RAW_DIR / "players"
MATCH_DIR  = RAW_DIR / "matches"
RESULT_DIR = RAW_DIR / "results"

for _d in [PLAYER_DIR, MATCH_DIR, RESULT_DIR]:
    _d.mkdir(parents=True, exist_ok=True)


# ─────────────────────────────────────────────────────────────
# ID 해석 유틸
# ─────────────────────────────────────────────────────────────

def _find_numeric_id_from_page(external_url: str) -> Optional[str]:
    """oopy.io 대회 공지 페이지에서 BAEF 백엔드 숫자형 contest_id 추출.

    탐색 전략:
      1. __NEXT_DATA__ JSON 전체에서 badmintonfriends 관련 URL 패턴 검색
      2. 페이지 HTML 전체에서 BAEF 관련 URL 패턴 검색
      3. BAEF 리스트 API에서 대회명으로 검색
    """
    try:
        resp = requests.get(external_url, headers=WEB_HEADERS, timeout=15, verify=False)
        html = resp.content.decode("utf-8", errors="replace")
        soup = BeautifulSoup(html, "html.parser")

        # ── 전략 1: __NEXT_DATA__ 안의 URL 패턴 ─────────────────
        script = soup.find("script", id="__NEXT_DATA__")
        if script and script.string:
            text = script.string
            for pat in [
                r'badmintonfriends\.co\.kr/comp/(?:v2/)?detail/(\d+)',
                r'badmintonfriends\.co\.kr/comp/apply/team/list/(\d+)',
                r'badmintonfriends\.co\.kr/comp/matchtable/tab/(\d+)',
                r'"COMP_PK"\s*:\s*(\d+)',
                r'"compPk"\s*:\s*(\d+)',
                r'"/comp/(\d+)"',
                r'comp\\?/(\d+)',
            ]:
                m = re.search(pat, text)
                if m:
                    return m.group(1)

        # ── 전략 2: HTML 전체에서 패턴 ───────────────────────────
        for pat in [
            r'real\.badmintonfriends\.co\.kr/comp/(?:v2/)?detail/(\d+)',
            r'badmintonfriends\.co\.kr/comp/(?!v2)(\d+)',
        ]:
            m = re.search(pat, html)
            if m:
                return m.group(1)

    except Exception as e:
        print(f"    [!] 페이지 파싱 실패 ({external_url}): {e}")

    return None


def _find_numeric_id_from_api(comp_name: str) -> Optional[str]:
    """BAEF 대회 목록 API에서 대회명으로 숫자 ID 검색 (fallback).

    가능한 status 값: end(종료), ing(진행중), ready(접수중)
    API 응답의 실제 필드명을 동적으로 탐색하여 PK를 추출한다.
    """
    for status in ("end", "ing", "ready"):
        try:
            url = "https://real.badmintonfriends.co.kr/comp/list"
            resp = requests.get(
                url, headers=API_HEADERS,
                params={"status": status, "pageSize": 200, "orderBy": "desc"},
                timeout=10,
            ).json()
            if resp.get("resCode") != "001":
                print(f"    [!] comp/list({status}) resCode={resp.get('resCode')}")
                continue

            result = resp.get("result", {})
            # 응답 구조 파악을 위해 키 출력 (처음 한 번만)
            if not hasattr(_find_numeric_id_from_api, "_keys_logged"):
                _find_numeric_id_from_api._keys_logged = True
                print(f"    [debug] comp/list result keys: {list(result.keys())[:10]}")
                # 첫 번째 아이템 키도 출력
                comp_list_key = next((k for k in result if isinstance(result[k], list)), None)
                if comp_list_key:
                    items = result[comp_list_key]
                    if items:
                        print(f"    [debug] 아이템 키: {list(items[0].keys())[:15]}")

            # 리스트 키 자동 탐색
            comp_list = None
            for key in result:
                if isinstance(result[key], list) and result[key]:
                    comp_list = result[key]
                    break

            if not comp_list:
                continue

            def _normalize(s: str) -> str:
                """비교용 정규화: 공백·특수문자 압축, 소문자화"""
                return re.sub(r'[\s\-_×X]+', ' ', s).strip().lower()

            target_norm = _normalize(comp_name)

            for item in comp_list:
                title = str(item.get("TITLE") or item.get("COMP_TITLE") or item.get("NAME") or "")
                # 완전 일치 우선, 실패 시 정규화 비교
                if title.strip() != comp_name.strip() and _normalize(title) != target_norm:
                    continue
                # PK 필드 자동 탐색 (알려진 키 + 숫자 값 전체 스캔)
                for pk_key in ("PK", "COMP_PK", "ID", "CONTEST_ID", "COMP_ID", "SEQ"):
                    pk = item.get(pk_key)
                    if pk and str(pk).isdigit():
                        return str(pk)
                # 알려진 키에 없으면 모든 필드에서 숫자 스캔
                for k, v in item.items():
                    if isinstance(v, int) and 100 <= v <= 9999:
                        return str(v)
                print(f"    [debug] 대회 찾았지만 PK 없음: {list(item.keys())[:15]}")

        except Exception as e:
            print(f"    [!] comp/list({status}) 예외: {e}")

    return None


# ─────────────────────────────────────────────────────────────
# 수집 함수  (numeric_id=API용, file_id=UUID=파일명·DB 매핑용)
# ─────────────────────────────────────────────────────────────

def extract_pks(detail_result):
    pks = []
    try:
        for gubun in detail_result.get("PROGRESS_GUBUN_LIST", []):
            for grade in gubun.get("GRADE_LIST", []):
                age_pk = grade.get("AGE_PK")
                if age_pk:
                    pks.append(str(age_pk))
        return ",".join(pks) if pks else "", list(set(pks))
    except Exception as e:
        print(f"    [!] PK 추출 에러: {e}")
        return "", []


def scrape_players(numeric_id: str, file_id: str, concat_pk: str, comp_name: str):
    """참가자 명단 수집. 파일명은 file_id(UUID) 기준."""
    output_file = PLAYER_DIR / f"baef_players_{file_id}.jsonl"
    url = f"https://real.badmintonfriends.co.kr/comp/apply/team/list/{numeric_id}"
    offset_no = total_saved = 0

    with open(output_file, "w", encoding="utf-8") as f:
        while True:
            try:
                res = requests.post(
                    url,
                    params={"offsetNo": offset_no, "orderBy": "desc"},
                    headers=API_HEADERS,
                    json={"CONCAT_PK": concat_pk},
                    timeout=15,
                ).json()
                teams = res.get("result", {}).get("APPLY_INFO_LIST", [])
                if not teams:
                    break

                for team in teams:
                    details = team.get("TEAM_DETAIL_LIST", [])
                    p1 = details[0] if len(details) > 0 else {}
                    p2 = details[1] if len(details) > 1 else {}

                    p1_name = (p1.get("NM") or p1.get("NAME") or
                               team.get("PLAYER1_NAME") or team.get("MBER_NM") or "")
                    p2_name = (p2.get("NM") or p2.get("NAME") or
                               team.get("PLAYER2_NAME") or team.get("PARTNER_NM") or "")

                    if p1_name or p2_name:
                        f.write(json.dumps({
                            "contest_id":          file_id,     # UUID (DB 매핑용)
                            "contest_title":       comp_name,
                            "category_full":       team.get("GRADE_TEXT") or team.get("GRADE_AGE_TEXT") or "",
                            "player1_name":        p1_name,
                            "player1_affiliation": p1.get("GROUP_NAME") or p1.get("CLB_NM") or "",
                            "player2_name":        p2_name,
                            "player2_affiliation": p2.get("GROUP_NAME") or p2.get("CLB_NM") or "",
                            "source":              "BAEF",
                        }, ensure_ascii=False) + "\n")
                        total_saved += 1

                offset_no += len(teams)
                time.sleep(0.3)
            except Exception:
                break

    print(f"    [v] 참가자 명단: {total_saved}명 수집")
    return total_saved


def scrape_match_history(numeric_id: str, file_id: str, comp_name: str):
    """매치 히스토리 수집. 파일명은 file_id(UUID) 기준."""
    tab_url = f"https://real.badmintonfriends.co.kr/comp/matchtable/tab/{numeric_id}"
    output_file = MATCH_DIR / f"baef_matches_{file_id}.jsonl"
    total_matches = 0

    try:
        res = requests.get(tab_url, headers=API_HEADERS, timeout=10).json()
        tabs = res.get("result", {}).get("COMP_MATCH_TEXT_LIST", [])

        with open(output_file, "w", encoding="utf-8") as f:
            for tab in tabs:
                for grade in tab.get("GRADE_AGE_LIST", []):
                    age_pk     = grade.get("AGE_PK")
                    grade_text = grade.get("GRADE_AGE_TEXT", "알수없음")
                    for info in grade.get("INFO_LIST", []):
                        info_pk      = info.get("INFO_PK")
                        bracket_type = info.get("TYPE_VAL_TEXT", "")
                        if not (age_pk and info_pk):
                            continue

                        list_url = (
                            f"https://real.badmintonfriends.co.kr"
                            f"/comp/intime/v2/apply/individual/match/info/list/{numeric_id}/N"
                        )
                        try:
                            match_res = requests.post(
                                list_url, headers=API_HEADERS,
                                json={"AGE_PK": int(age_pk), "INFO_PK": int(info_pk)},
                                timeout=10,
                            ).json()
                            raw_data = match_res.get("result", {})
                            items = (
                                raw_data if isinstance(raw_data, list)
                                else (raw_data.get("MATCH_LIST") or
                                      raw_data.get("MATCH_INFO_LIST") or
                                      ([raw_data] if isinstance(raw_data, dict) else []))
                            )
                            for m_data in items:
                                if m_data:
                                    f.write(json.dumps({
                                        "contest_id":    file_id,
                                        "contest_title": comp_name,
                                        "category":      grade_text,
                                        "bracket":       bracket_type,
                                        "match_detail":  m_data,
                                    }, ensure_ascii=False) + "\n")
                                    total_matches += 1
                        except Exception:
                            continue
                        time.sleep(0.2)
    except Exception:
        pass

    print(f"    [v] 전적 스코어: {total_matches}경기 수집")


def scrape_final_ranks(numeric_id: str, file_id: str, age_pks: list, comp_name: str):
    """최종 입상자 수집. 파일명은 file_id(UUID) 기준."""
    output_file = RESULT_DIR / f"results_{file_id}.jsonl"
    total_saved = 0

    with open(output_file, "w", encoding="utf-8") as f:
        for age_pk in age_pks:
            url = (
                f"https://real.badmintonfriends.co.kr"
                f"/comp/intime/apply/match/result/{numeric_id}/team"
            )
            try:
                res = requests.get(
                    url, headers=API_HEADERS,
                    params={"agePk": age_pk},
                    timeout=10,
                ).json()
                rank_lists = res.get("result", {}).get("MATCH_RANK_LIST", [])
                for match_group in rank_lists:
                    category = match_group.get("GUBUN_FULL_TEXT", "알수없음")
                    for item in match_group.get("RANK_LIST", []):
                        det = item.get("TEAM_DETAIL_LIST", [])
                        p1, p2 = (det[0] if len(det) > 0 else {}), (det[1] if len(det) > 1 else {})
                        p1_n = p1.get("NM") or p1.get("NAME") or item.get("TEAM_NAME") or item.get("NM")
                        p2_n = p2.get("NM") or p2.get("NAME")
                        if p1_n or p2_n:
                            f.write(json.dumps({
                                "contest_id":    file_id,
                                "contest_title": comp_name,
                                "category":      category,
                                "rank_text":     item.get("WIN_TYPE_TEXT", ""),
                                "p1_name":       p1_n,
                                "p1_group":      p1.get("GROUP_NAME"),
                                "p2_name":       p2_n,
                                "p2_group":      p2.get("GROUP_NAME"),
                            }, ensure_ascii=False) + "\n")
                            total_saved += 1
            except Exception:
                pass
            time.sleep(0.2)

    print(f"    [v] 최종 입상자: {total_saved}명 수집")


# ─────────────────────────────────────────────────────────────
# 메인 헌터
# ─────────────────────────────────────────────────────────────

def run_baef_stats_hunter(target_ids: list) -> list:
    """지정된 대회 UUID 목록의 3대 전적 데이터를 수집합니다.

    target_ids : Tournament.external_id 값 (UUID 문자열 목록)
    반환       : 수집 성공한 UUID 문자열 리스트
                 (collect_stats.py 가 이 값으로 is_stats_fetched 마킹)
    """
    print(f"=== BAEF Stats Hunter Started (타겟 {len(target_ids)}개) ===")
    success_ids = []

    # Django ORM으로 external_url + name 일괄 조회
    try:
        from core.models import Tournament
        tournament_map = {
            t.external_id: {"url": t.external_url, "name": t.name}
            for t in Tournament.objects.filter(source="BAEF", external_id__in=target_ids)
        }
    except Exception as e:
        print(f"  [!] Tournament 조회 실패: {e}")
        tournament_map = {}

    for contest_uuid in target_ids:
        print(f"\n── [{contest_uuid[:8]}...] 처리 시작")

        # ── Step 1: UUID → 숫자 ID 해석 ───────────────────────────
        numeric_id: Optional[str] = None
        t_info = tournament_map.get(contest_uuid, {})
        external_url = t_info.get("url", "")
        t_name = t_info.get("name", "")

        # 전략 A: 대회 공지 페이지 파싱
        if external_url:
            print(f"  [*] 숫자 ID 탐색 (페이지): {external_url}")
            numeric_id = _find_numeric_id_from_page(external_url)

        # 전략 B: BAEF API 목록에서 이름으로 검색
        if not numeric_id and t_name:
            print(f"  [*] 숫자 ID 탐색 (API 이름 검색): {t_name[:40]}")
            numeric_id = _find_numeric_id_from_api(t_name)

        if numeric_id:
            print(f"  [*] 숫자 ID 확인: {numeric_id}")
        else:
            print(f"  [!] 숫자 ID 찾기 실패 → 스킵: {contest_uuid}")
            continue

        # ── Step 2: BAEF API로 상세 정보 및 PK 획득 ────────────────
        detail_url = f"https://real.badmintonfriends.co.kr/comp/v2/detail/{numeric_id}"
        try:
            res_json = requests.get(detail_url, headers=API_HEADERS, timeout=10).json()
            if res_json.get("resCode") != "001" or not res_json.get("result"):
                print(f"  [!] API 응답 오류: resCode={res_json.get('resCode')}, msg={res_json.get('resMsg','')}")
                continue

            result    = res_json.get("result", {})
            comp_name = result.get("TITLE", f"BAEF_{numeric_id}")
            print(f"  [+] 대회 확인: {comp_name}")

            concat_pk, age_pks = extract_pks(result)

            if concat_pk and age_pks:
                # ── Step 3: 3대 데이터 수집 (JSONL은 UUID 기준으로 저장)
                player_cnt = scrape_players(numeric_id, contest_uuid, concat_pk, comp_name)
                scrape_match_history(numeric_id, contest_uuid, comp_name)
                scrape_final_ranks(numeric_id, contest_uuid, age_pks, comp_name)

                if player_cnt > 0:
                    success_ids.append(str(contest_uuid))
                else:
                    print(f"  [-] 참가자 0명 → 성공 처리 안 함")
            else:
                print(f"  [-] 종목(PK) 정보 없음 → 스킵")

            time.sleep(1.0)

        except Exception as e:
            print(f"  [!] 에러 발생: {e}")

    print(f"\n=== BAEF Stats Hunter Done — 성공 {len(success_ids)}/{len(target_ids)}개 ===")
    return success_ids


if __name__ == "__main__":
    # 단독 테스트: 숫자 ID 로 직접 실행 가능
    # 예) python status_baef.py
    test_numeric_ids = [215, 278]
    for nid in test_numeric_ids:
        run_baef_stats_hunter([str(nid)])
