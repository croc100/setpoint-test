import os
import sys
import time
import requests
import json
from pathlib import Path
from dotenv import load_dotenv  # <-- 이게 빠지면 NameError 발생함

# [환경 설정]
BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if BASE_DIR not in sys.path:
    sys.path.append(BASE_DIR)

# .env 경로 설정 및 로드
env_path = os.path.join(BASE_DIR, ".env")
load_dotenv(env_path)

# 환경 변수 할당
BADDY_TOKEN = os.environ.get("BADDY_TOKEN", "")

# 검증 로그
if not BADDY_TOKEN:
    print(f"[!] 경고: BADDY_TOKEN을 찾을 수 없음 (확인 경로: {env_path})")
else:
    print(f"[*] 환경 변수 로드 성공 (Token: {BADDY_TOKEN[:10]}...)")
    
HEADERS = {
    "accept-encoding": "gzip",
    "content-type": "application/json",
    "cookie": f"BADDY_TOKEN={BADDY_TOKEN}",
    "host": "real.badmintonfriends.co.kr",
    "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/120.0.0.0 Safari/537.36"
}

# [데이터 저장소]
RAW_DIR = Path(BASE_DIR) / "data" / "raw"
PLAYER_DIR = RAW_DIR / "players"
MATCH_DIR = RAW_DIR / "matches"
RESULT_DIR = RAW_DIR / "results"

for d in [PLAYER_DIR, MATCH_DIR, RESULT_DIR]:
    d.mkdir(parents=True, exist_ok=True)

def extract_pks(detail_result):
    pks = []
    try:
        for gubun in detail_result.get("PROGRESS_GUBUN_LIST", []):
            for grade in gubun.get("GRADE_LIST", []):
                age_pk = grade.get("AGE_PK")
                if age_pk: pks.append(str(age_pk))
        return ",".join(pks) if pks else "", list(set(pks))
    except Exception as e:
        print(f"    [!] PK 추출 에러: {e}")
        return "", []

def scrape_players(contest_id, concat_pk, comp_name):
    output_file = PLAYER_DIR / f"baef_players_{contest_id}.jsonl"
    url = f"https://real.badmintonfriends.co.kr/comp/apply/team/list/{contest_id}"
    offset_no, total_saved = 0, 0
    
    with open(output_file, "w", encoding="utf-8") as f:
        while True:
            try:
                res = requests.post(url, params={"offsetNo": offset_no, "orderBy": "desc"}, 
                                    headers=HEADERS, json={"CONCAT_PK": concat_pk}, timeout=15).json()
                teams = res.get("result", {}).get("APPLY_INFO_LIST", [])
                if not teams: break
                
                for team in teams:
                    details = team.get("TEAM_DETAIL_LIST", [])
                    p1 = details[0] if len(details) > 0 else {}
                    p2 = details[1] if len(details) > 1 else {}
                    
                    p1_name = p1.get("NM") or p1.get("NAME") or team.get("PLAYER1_NAME") or team.get("MBER_NM") or ""
                    p2_name = p2.get("NM") or p2.get("NAME") or team.get("PLAYER2_NAME") or team.get("PARTNER_NM") or ""
                    
                    if p1_name or p2_name:
                        f.write(json.dumps({
                            "contest_id": str(contest_id), "contest_title": comp_name,
                            "category_full": team.get("GRADE_TEXT") or team.get("GRADE_AGE_TEXT") or "",
                            "player1_name": p1_name, "player1_affiliation": p1.get("GROUP_NAME") or p1.get("CLB_NM") or "",
                            "player2_name": p2_name, "player2_affiliation": p2.get("GROUP_NAME") or p2.get("CLB_NM") or "",
                            "source": "BAEF"
                        }, ensure_ascii=False) + "\n")
                        total_saved += 1
                offset_no += len(teams)
                time.sleep(0.3)
            except Exception: break
    print(f"    [v] 참가자 명단: {total_saved}명 수집")

def scrape_match_history(contest_id, comp_name):
    tab_url = f"https://real.badmintonfriends.co.kr/comp/matchtable/tab/{contest_id}"
    output_file = MATCH_DIR / f"baef_matches_{contest_id}.jsonl"
    total_matches = 0
    
    try:
        res = requests.get(tab_url, headers=HEADERS, timeout=10).json()
        tabs = res.get("result", {}).get("COMP_MATCH_TEXT_LIST", [])
        
        with open(output_file, "w", encoding="utf-8") as f:
            for tab in tabs:
                for grade in tab.get("GRADE_AGE_LIST", []):
                    age_pk, grade_text = grade.get("AGE_PK"), grade.get("GRADE_AGE_TEXT", "알수없음")
                    for info in grade.get("INFO_LIST", []):
                        info_pk, bracket_type = info.get("INFO_PK"), info.get("TYPE_VAL_TEXT", "")
                        if not (age_pk and info_pk): continue
                        
                        list_url = f"https://real.badmintonfriends.co.kr/comp/intime/v2/apply/individual/match/info/list/{contest_id}/N"
                        try:
                            match_res = requests.post(list_url, headers=HEADERS, json={"AGE_PK": int(age_pk), "INFO_PK": int(info_pk)}, timeout=10).json()
                            raw_data = match_res.get("result", {})
                            items = raw_data if isinstance(raw_data, list) else (raw_data.get("MATCH_LIST") or raw_data.get("MATCH_INFO_LIST") or [raw_data] if isinstance(raw_data, dict) else [])
                            for m_data in items:
                                if m_data:
                                    f.write(json.dumps({"contest_id": str(contest_id), "contest_title": comp_name, "category": grade_text, "bracket": bracket_type, "match_detail": m_data}, ensure_ascii=False) + "\n")
                                    total_matches += 1
                        except: continue
                        time.sleep(0.2)
    except: pass
    print(f"    [v] 전적 스코어: {total_matches}경기 수집")

def scrape_final_ranks(contest_id, age_pks, comp_name):
    output_file = RESULT_DIR / f"results_{contest_id}.jsonl"
    total_saved = 0
    
    with open(output_file, "w", encoding="utf-8") as f:
        for age_pk in age_pks:
            url = f"https://real.badmintonfriends.co.kr/comp/intime/apply/match/result/{contest_id}/team"
            try:
                res = requests.get(url, headers=HEADERS, params={"agePk": age_pk}, timeout=10).json()
                rank_lists = res.get("result", {}).get("MATCH_RANK_LIST", [])
                for match_group in rank_lists:
                    category = match_group.get("GUBUN_FULL_TEXT", "알수없음")
                    for item in match_group.get("RANK_LIST", []):
                        det = item.get("TEAM_DETAIL_LIST", [])
                        p1, p2 = (det[0] if len(det)>0 else {}), (det[1] if len(det)>1 else {})
                        p1_n = p1.get("NM") or p1.get("NAME") or item.get("TEAM_NAME") or item.get("NM")
                        p2_n = p2.get("NM") or p2.get("NAME")
                        if p1_n or p2_n:
                            f.write(json.dumps({"contest_id": str(contest_id), "contest_title": comp_name, "category": category, "rank_text": item.get("WIN_TYPE_TEXT", ""), "p1_name": p1_n, "p1_group": p1.get("GROUP_NAME"), "p2_name": p2_n, "p2_group": p2.get("GROUP_NAME")}, ensure_ascii=False) + "\n")
                            total_saved += 1
            except: pass
            time.sleep(0.2)
    print(f"    [v] 최종 입상자: {total_saved}명 수집")

def run_baef_stats_hunter(target_ids: list) -> list:
    """지정된 대회 ID들의 3대 전적 데이터를 긁어옵니다.

    반환: 수집 성공한 contest_id 문자열 리스트
    (collect_stats.py 가 이 값을 보고 is_stats_fetched 마킹 여부 결정)
    """
    print(f"=== BAEF Stats Hunter Started (타겟 {len(target_ids)}개) ===")
    success_ids = []

    for contest_id in target_ids:
        detail_url = f"https://real.badmintonfriends.co.kr/comp/v2/detail/{contest_id}"
        try:
            res_json = requests.get(detail_url, headers=HEADERS, timeout=10).json()
            if res_json.get("resCode") != "001" or not res_json.get("result"):
                continue

            result = res_json.get("result", {})
            comp_name = result.get("TITLE", f"Unknown_{contest_id}")
            print(f"\n[+] 딥다이브 타겟 포착: {comp_name} (ID: {contest_id})")

            concat_pk, age_pks = extract_pks(result)

            if concat_pk and age_pks:
                scrape_players(contest_id, concat_pk, comp_name)
                scrape_match_history(contest_id, comp_name)
                scrape_final_ranks(contest_id, age_pks, comp_name)
                success_ids.append(str(contest_id))   # ← 성공 ID 기록
            else:
                print(f"    [-] 종목(PK) 정보가 없어 수집을 스킵함.")
            time.sleep(1.0)

        except Exception as e:
            print(f"    [!] 에러 발생 (ID {contest_id}): {e}")

    print(f"\n=== BAEF Stats Hunter Done — 성공 {len(success_ids)}/{len(target_ids)}개 ===")
    return success_ids

if __name__ == "__main__":
    # [수동 테스트] 긁어올 대회 ID 리스트를 여기에 넣습니다.
    # 예: 방금 base.py로 찾은 BAEF 최신 대회 ID들
    test_target_ids = [215, 278, 290] 
    run_baef_stats_hunter(test_target_ids)