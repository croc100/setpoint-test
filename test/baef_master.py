import time
import requests
import json
from pathlib import Path

# [설정값] 최신 JWT 토큰
BADDY_TOKEN = "eyJyZWdEYXRlIjoxNzc2Mjc2MzU0MjIzLCJ0eXAiOiJKV1QiLCJhbGciOiJIUzI1NiJ9.eyJtYmVyTm8iOjQ5OTAyLCJleHAiOjE3NzYzNjI3NTR9.8E-AyaLevSUOzcEZq0iS64J1HDVpDv4F5sIGa4v05Go"

HEADERS = {
    "accept-encoding": "gzip",
    "content-type": "application/json",
    "cookie": f"BADDY_TOKEN={BADDY_TOKEN}",
    "host": "real.badmintonfriends.co.kr",
    "user-agent": "Dart/3.6 (dart:io)"
}

# [경로 설정] 3대 핵심 데이터 디렉토리 분리
PLAYER_DIR = Path("data/raw/players")
MATCH_DIR = Path("data/raw/matches")
RESULT_DIR = Path("data/raw/results")

for d in [PLAYER_DIR, MATCH_DIR, RESULT_DIR]:
    d.mkdir(parents=True, exist_ok=True)

def extract_pks(detail_result):
    """대회 상세 정보에서 CONCAT_PK(참가자용)와 AGE_PK_LIST(결과용) 동시 추출"""
    pks = []
    try:
        for gubun in detail_result.get("PROGRESS_GUBUN_LIST", []):
            for grade in gubun.get("GRADE_LIST", []):
                age_pk = grade.get("AGE_PK")
                if age_pk:
                    pks.append(str(age_pk))
        
        concat_pk = ",".join(pks) if pks else ""
        return concat_pk, list(set(pks)) # 중복 제거된 리스트도 반환
    except Exception as e:
        print(f"    [!] PK 추출 에러: {e}")
        return "", []

def scrape_players(contest_id, concat_pk, comp_name):
    """[수집 모듈 1] 전체 참가자 명단 수집"""
    output_file = PLAYER_DIR / f"baef_players_{contest_id}.jsonl"
    url = f"https://real.badmintonfriends.co.kr/comp/apply/team/list/{contest_id}"
    
    offset_no, total_saved = 0, 0
    with open(output_file, "w", encoding="utf-8") as f:
        while True:
            params = {"offsetNo": offset_no, "orderBy": "desc"}
            payload = {"CONCAT_PK": concat_pk}
            try:
                res = requests.post(url, params=params, headers=HEADERS, json=payload, timeout=15).json()
                teams = res.get("result", {}).get("APPLY_INFO_LIST", [])
                if not teams: break
                
                for team in teams:
                    details = team.get("TEAM_DETAIL_LIST", [])
                    p1 = details[0] if len(details) > 0 else {}
                    p2 = details[1] if len(details) > 1 else {}
                    
                    p1_name = p1.get("NM") or p1.get("NAME") or team.get("PLAYER1_NAME") or team.get("MBER_NM") or ""
                    p2_name = p2.get("NM") or p2.get("NAME") or team.get("PLAYER2_NAME") or team.get("PARTNER_NM") or ""
                    
                    if p1_name or p2_name:
                        record = {
                            "contest_id": str(contest_id),
                            "contest_title": comp_name,
                            "category_full": team.get("GRADE_TEXT") or team.get("GRADE_AGE_TEXT") or "",
                            "player1_name": p1_name,
                            "player1_affiliation": p1.get("GROUP_NAME") or p1.get("CLB_NM") or "",
                            "player2_name": p2_name,
                            "player2_affiliation": p2.get("GROUP_NAME") or p2.get("CLB_NM") or "",
                            "source": "BAEF"
                        }
                        f.write(json.dumps(record, ensure_ascii=False) + "\n")
                        total_saved += 1
                
                offset_no += len(teams)
                time.sleep(0.3)
            except Exception as e:
                break
    print(f"    [v] 참가자 명단: {total_saved}명 수집")

def scrape_match_history(contest_id, comp_name):
    """[수집 모듈 2] 조별/본선 상세 스코어 대진 수집"""
    tab_url = f"https://real.badmintonfriends.co.kr/comp/matchtable/tab/{contest_id}"
    output_file = MATCH_DIR / f"baef_matches_{contest_id}.jsonl"
    total_matches = 0
    
    try:
        res = requests.get(tab_url, headers=HEADERS, timeout=10).json()
        tabs = res.get("result", {}).get("COMP_MATCH_TEXT_LIST", [])
        
        with open(output_file, "w", encoding="utf-8") as f:
            for tab in tabs:
                for grade in tab.get("GRADE_AGE_LIST", []):
                    age_pk = grade.get("AGE_PK")
                    grade_text = grade.get("GRADE_AGE_TEXT", "알수없음")
                    for info in grade.get("INFO_LIST", []):
                        info_pk, bracket_type = info.get("INFO_PK"), info.get("TYPE_VAL_TEXT", "")
                        if not (age_pk and info_pk): continue
                        
                        list_url = f"https://real.badmintonfriends.co.kr/comp/intime/v2/apply/individual/match/info/list/{contest_id}/N"
                        payload = {"AGE_PK": int(age_pk), "INFO_PK": int(info_pk)}
                        try:
                            match_res = requests.post(list_url, headers=HEADERS, json=payload, timeout=10).json()
                            raw_data = match_res.get("result", {})
                            items = raw_data if isinstance(raw_data, list) else (raw_data.get("MATCH_LIST") or raw_data.get("MATCH_INFO_LIST") or [raw_data] if isinstance(raw_data, dict) else [])
                            
                            for match_data in items:
                                if not match_data: continue
                                f.write(json.dumps({
                                    "contest_id": str(contest_id), "contest_title": comp_name,
                                    "category": grade_text, "bracket": bracket_type, "match_detail": match_data
                                }, ensure_ascii=False) + "\n")
                                total_matches += 1
                        except: continue
                        time.sleep(0.2)
    except: pass
    print(f"    [v] 전적 스코어: {total_matches}경기 수집")

def scrape_final_ranks(contest_id, age_pks, comp_name):
    """[수집 모듈 3] 1~3위, 8강/16강 최종 입상 명단 수집"""
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
                            f.write(json.dumps({
                                "contest_id": str(contest_id), "contest_title": comp_name,
                                "category": category, "rank_text": item.get("WIN_TYPE_TEXT", ""),
                                "p1_name": p1_n, "p1_group": p1.get("GROUP_NAME"),
                                "p2_name": p2_n, "p2_group": p2.get("GROUP_NAME")
                            }, ensure_ascii=False) + "\n")
                            total_saved += 1
            except: pass
            time.sleep(0.2)
    print(f"    [v] 최종 입상자: {total_saved}명 수집")

def run_master_engine(start_id, end_id):
    """메인 루프: 3대 데이터 일괄 수집 오케스트레이션"""
    print(f"=== BAEF Master Engine Started ({start_id} ~ {end_id}) ===")
    
    for contest_id in range(start_id, end_id + 1):
        detail_url = f"https://real.badmintonfriends.co.kr/comp/v2/detail/{contest_id}"
        try:
            res_json = requests.get(detail_url, headers=HEADERS, timeout=10).json()
            if res_json.get("resCode") != "001" or not res_json.get("result"):
                continue # 대회가 없으면 조용히 패스
            
            result = res_json.get("result", {})
            comp_name = result.get("TITLE", f"Unknown_{contest_id}")
            print(f"\n[+] 타겟 포착: {comp_name} (ID: {contest_id})")
            
            # 1. 상세정보 JSON 백업
            with open(PLAYER_DIR / f"debug_detail_{contest_id}.json", "w", encoding="utf-8") as f:
                json.dump(result, f, ensure_ascii=False, indent=2)
            
            # 2. PK 추출 (참가자용 concat, 성적용 리스트)
            concat_pk, age_pks = extract_pks(result)
            
            # 3. 3대 수집 모듈 순차 실행
            if concat_pk and age_pks:
                scrape_players(contest_id, concat_pk, comp_name)
                scrape_match_history(contest_id, comp_name)
                scrape_final_ranks(contest_id, age_pks, comp_name)
            else:
                print(f"    [-] 종목(PK) 정보가 없어 수집을 스킵함.")
            
            time.sleep(1.0) # 서버 차단 방지용 안전 쿨타임
            
        except Exception as e:
            print(f"    [!] Fatal error at ID {contest_id}: {e}")

if __name__ == "__main__":
    # 테스트 구간 (원하는 범위로 수정해서 사용)
    run_master_engine(215, 280)