import time
import requests
import json
from pathlib import Path

# [설정] 캡처된 토큰
BADDY_TOKEN = "eyJyZWdEYXRlIjoxNzc2Mjc2MzU0MjIzLCJ0eXAiOiJKV1QiLCJhbGciOiJIUzI1NiJ9.eyJtYmVyTm8iOjQ5OTAyLCJleHAiOjE3NzYzNjI3NTR9.8E-AyaLevSUOzcEZq0iS64J1HDVpDv4F5sIGa4v05Go"

HEADERS = {
    "accept-encoding": "gzip",
    "content-type": "application/json",
    "cookie": f"BADDY_TOKEN={BADDY_TOKEN}",
    "host": "real.badmintonfriends.co.kr",
    "user-agent": "Dart/3.6 (dart:io)"
}

RESULT_DIR = Path("data/raw/results")
RESULT_DIR.mkdir(parents=True, exist_ok=True)

def get_active_tournaments():
    """Step 1: v3/list API에서 전체 대회 목록 추출"""
    url = "https://real.badmintonfriends.co.kr/comp/v3/list"
    try:
        res = requests.get(url, headers=HEADERS, timeout=10).json()
        result_data = res.get("result", {})
        if isinstance(result_data, dict):
            return result_data.get("COMP_LIST", [])
        elif isinstance(result_data, list):
            return result_data
        return []
    except Exception as e:
        print(f"[!] 대회 목록 로드 실패: {e}")
        return []

def get_age_pks(contest_id):
    """Step 2: 특정 대회의 모든 종목(agePk) 추출"""
    url = f"https://real.badmintonfriends.co.kr/comp/v2/detail/{contest_id}"
    try:
        res = requests.get(url, headers=HEADERS, timeout=10).json()
        result = res.get("result", {})
        title = result.get("TITLE", f"Unknown_Contest_{contest_id}")
        
        pks = []
        for gubun in result.get("PROGRESS_GUBUN_LIST", []):
            for grade in gubun.get("GRADE_LIST", []):
                pk = grade.get("AGE_PK")
                if pk: pks.append(str(pk))
                
        return list(set(pks)), title # 중복 제거 후 반환
    except Exception as e:
        return [], ""

def fetch_and_save_ranks(contest_id, age_pk, contest_title):
    """Step 3: 단일 종목의 순위 데이터 추출 (강력한 예외 처리 적용)"""
    url = f"https://real.badmintonfriends.co.kr/comp/intime/apply/match/result/{contest_id}/team"
    params = {"agePk": age_pk}
    
    try:
        response = requests.get(url, headers=HEADERS, params=params, timeout=10)
        res = response.json()
        rank_lists = res.get("result", {}).get("MATCH_RANK_LIST", [])
        
        records = []
        for match_group in rank_lists:
            category = match_group.get("GUBUN_FULL_TEXT", "알수없음")
            for rank_item in match_group.get("RANK_LIST", []):
                win_text = rank_item.get("WIN_TYPE_TEXT", "")
                details = rank_item.get("TEAM_DETAIL_LIST", [])
                
                # [핵심 변경점] 이름 추출 다중 방어 로직 (null 방지)
                p1_name, p2_name = None, None
                p1_group, p2_group = None, None

                if details:
                    p1_obj = details[0] if len(details) > 0 else {}
                    p2_obj = details[1] if len(details) > 1 else {}
                    
                    p1_name = p1_obj.get("NM") or p1_obj.get("NAME") or p1_obj.get("MBER_NM")
                    p1_group = p1_obj.get("GROUP_NAME") or p1_obj.get("CLB_NM")
                    
                    p2_name = p2_obj.get("NM") or p2_obj.get("NAME") or p2_obj.get("MBER_NM")
                    p2_group = p2_obj.get("GROUP_NAME") or p2_obj.get("CLB_NM")

                # details 배열에 이름이 없을 경우 rank_item 본체에서 직접 탐색 (단체전 등)
                if not p1_name:
                    p1_name = rank_item.get("TEAM_NAME") or rank_item.get("MBER_NM") or rank_item.get("NM")
                if not p2_name:
                    # 단체전은 팀 이름만 있는 경우가 많으므로 p2는 비워둘 수 있음
                    pass
                
                record = {
                    "contest_id": str(contest_id),
                    "contest_title": contest_title,
                    "category": category,
                    "rank_text": win_text,
                    "p1_name": p1_name,
                    "p1_group": p1_group,
                    "p2_name": p2_name,
                    "p2_group": p2_group
                }
                records.append(record)
        
        if records:
            output_path = RESULT_DIR / f"results_{contest_id}.jsonl"
            with open(output_path, "a", encoding="utf-8") as f:
                for rec in records:
                    f.write(json.dumps(rec, ensure_ascii=False) + "\n")
            return len(records)
    except Exception:
        return 0
    return 0

def run_rank_hunter():
    print(f"[*] BAEF 성적 수집 엔진 가동 (경로: {RESULT_DIR})")
    
    tournaments = get_active_tournaments()
    if not tournaments:
        print("[!] 수집 가능한 대회가 없습니다.")
        return

    print(f"[*] 총 {len(tournaments)}개 대회 타겟팅 완료. 분석 시작...\n")
    
    for comp in tournaments:
        cid = comp.get("PK") or comp.get("COMP_PK") or comp.get("id")
        if not cid:
            continue
            
        age_pks, title = get_age_pks(cid)
        
        if not age_pks:
            print(f"    [-] {title} (ID: {cid}) - 종목 정보 없음 스킵")
            continue
            
        total_saved = 0
        for apk in age_pks:
            count = fetch_and_save_ranks(cid, apk, title)
            total_saved += count
            time.sleep(0.2) # API 부하 방지
            
        print(f"    [v] {title}: 입상 기록 {total_saved}건 수집 완료")
        time.sleep(0.5)

if __name__ == "__main__":
    run_rank_hunter()