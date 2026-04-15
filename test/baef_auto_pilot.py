import time
import requests
import json
import os
from pathlib import Path

# [설정값] 최신 캡처 토큰 (유효기간 확인 필요)
BADDY_TOKEN = "eyJyZWdEYXRlIjoxNzc2Mjc2MzU0MjIzLCJ0eXAiOiJKV1QiLCJhbGciOiJIUzI1NiJ9.eyJtYmVyTm8iOjQ5OTAyLCJleHAiOjE3NzYzNjI3NTR9.8E-AyaLevSUOzcEZq0iS64J1HDVpDv4F5sIGa4v05Go"

HEADERS = {
    "accept-encoding": "gzip",
    "content-type": "application/json",
    "cookie": f"BADDY_TOKEN={BADDY_TOKEN}",
    "host": "real.badmintonfriends.co.kr",
    "user-agent": "Dart/3.6 (dart:io)"
}

# [경로 설정] raw/players 폴더 강제 지정
BASE_DIR = Path("data/raw/players")
BASE_DIR.mkdir(parents=True, exist_ok=True)

def get_active_tournaments():
    """Step 1: v3 API를 통해 현재 활성화된 대회 목록 ID 추출"""
    url = "https://real.badmintonfriends.co.kr/comp/v3/list"
    try:
        response = requests.get(url, headers=HEADERS, timeout=10)
        data = response.json()
        
        # [디버깅용] 필요 시 주석 해제하여 확인
        # print("-" * 50)
        # print("[DEBUG] API Raw Response:", json.dumps(data, ensure_ascii=False)[:500])
        # print("-" * 50)

        # 1. 'result' 키를 먼저 확보
        result_data = data.get("result", {})
        
        # 2. 'result'가 딕셔너리라면 내부의 'COMP_LIST'를 추출
        if isinstance(result_data, dict):
            tournaments = result_data.get("COMP_LIST", [])
        # 3. 만약 'result' 자체가 리스트라면 그대로 사용 (예외 케이스 대비)
        elif isinstance(result_data, list):
            tournaments = result_data
        else:
            tournaments = []
            
        return tournaments
    except Exception as e:
        print(f"[!] 대회 목록 로드 실패: {e}")
        return []
        
def extract_concat_pk(contest_id):
    """Step 2: 대회 상세 페이지에서 종목 PK(AGE_PK) 및 대회명 추출"""
    url = f"https://real.badmintonfriends.co.kr/comp/v2/detail/{contest_id}"
    try:
        res = requests.get(url, headers=HEADERS, timeout=10).json()
        result = res.get("result", {})
        
        # 디버깅용 상세 정보 저장 (raw/players/ 내부에 저장)
        with open(BASE_DIR / f"debug_detail_{contest_id}.json", "w", encoding="utf-8") as f:
            json.dump(result, f, ensure_ascii=False, indent=2)
            
        pks = []
        # PROGRESS_GUBUN_LIST -> GRADE_LIST -> AGE_PK 추출 로직
        for gubun in result.get("PROGRESS_GUBUN_LIST", []):
            for grade in gubun.get("GRADE_LIST", []):
                pk = grade.get("AGE_PK")
                if pk: pks.append(str(pk))
        
        # TITLE 키가 없을 경우를 대비해 예외 처리
        title = result.get("TITLE", f"Unknown_Contest_{contest_id}")
        return ",".join(pks), title
    except Exception as e:
        print(f"    [!] ID {contest_id} 상세 정보 추출 에러: {e}")
        return "", ""

def scrape_players(contest_id, concat_pk, title):
    """Step 3: 해당 대회의 모든 참가자 전적 수집"""
    output_file = BASE_DIR / f"baef_players_{contest_id}.jsonl"
    url = f"https://real.badmintonfriends.co.kr/comp/apply/team/list/{contest_id}"
    
    offset = 0
    total = 0
    
    # 새로운 파일로 시작 (Overwrite 모드 방지 위해 append 사용하되 실행 전 삭제 권장)
    with open(output_file, "w", encoding="utf-8") as f:
        while True:
            params = {"offsetNo": offset, "orderBy": "desc"}
            payload = {"CONCAT_PK": concat_pk}
            
            try:
                response = requests.post(url, params=params, headers=HEADERS, json=payload, timeout=15)
                res = response.json()
                teams = res.get("result", {}).get("APPLY_INFO_LIST", [])
                
                if not teams:
                    break
                
                for team in teams:
                    # 1. 선수 상세 리스트 확보
                    details = team.get("TEAM_DETAIL_LIST", [])
                    
                    # 2. 배프 API 특성상 이름 키값이 다를 수 있으므로 후보군을 다 훑음
                    # NM, NAME, MBER_NM 등 가능성 있는 키 확인
                    def get_name(p_obj):
                        return p_obj.get("NM") or p_obj.get("NAME") or p_obj.get("MBER_NM") or ""

                    def get_group(p_obj):
                        return p_obj.get("GROUP_NAME") or p_obj.get("CLB_NM") or ""

                    p1_obj = details[0] if len(details) > 0 else {}
                    p2_obj = details[1] if len(details) > 1 else {}
                    
                    p1_name = get_name(p1_obj)
                    p2_name = get_name(p2_obj)

                    # 만약 여전히 이름이 없다면? team 객체 바로 아래에 있는지 확인 (일부 API 규격)
                    if not p1_name:
                        p1_name = team.get("PLAYER1_NAME") or team.get("MBER_NM") or ""
                    if not p2_name:
                        p2_name = team.get("PLAYER2_NAME") or team.get("PARTNER_NM") or ""

                    record = {
                        "contest_id": str(contest_id),
                        "contest_title": title,
                        "category_full": team.get("GRADE_TEXT") or team.get("GRADE_AGE_TEXT") or "",
                        "player1_name": p1_name,
                        "player1_affiliation": get_group(p1_obj),
                        "player2_name": p2_name,
                        "player2_affiliation": get_group(p2_obj),
                        "source": "BAEF"
                    }
                    
                    # 이름이 최소한 하나라도 있어야 저장 (빈 데이터 방지)
                    if p1_name or p2_name:
                        f.write(json.dumps(record, ensure_ascii=False) + "\n")
                        total_saved += 1

                offset += len(teams)
                time.sleep(0.3) # 서버 부하 방지용 쿨타임
                
            except Exception as e:
                print(f"    [!] 데이터 수집 중 에러: {e}")
                break
                
    print(f"    [v] {title}: 총 {total}개 데이터 수집 완료")

def run_autopilot():
    print(f"[*] BAEF 수집 엔진 가동 (경로: {BASE_DIR})")
    tournaments = get_active_tournaments()
    
    if not tournaments:
        print("[!] 수집 가능한 대회가 없습니다.")
        return

    print(f"[*] 총 {len(tournaments)}개의 대회 타겟을 발견했습니다.")
    
    for comp in tournaments:
        # [수정 포인트] 모든 가능성 있는 ID 키를 순차적으로 확인
        cid = None
        if isinstance(comp, dict):
            # 순서대로 시도: COMP_PK, id, pk
            cid = comp.get("PK") or comp.get("COMP_PK") or comp.get("id")        
        else:
            cid = str(comp)
            
        # 디버깅: 만약 cid가 여전히 없다면 해당 객체의 키를 출력
        if not cid:
            print(f"    [!] ID를 찾을 수 없는 데이터 형식: {comp}")
            continue
            
        print(f"[*] 분석 시도 중... (ID: {cid})") # 이 로그가 찍혀야 정상입니다.
        cpk, title = extract_concat_pk(cid)
        
        if cpk:
            print(f"    [+] 스캔 중: {title} (ID: {cid})")
            scrape_players(cid, cpk, title)
        else:
            # 상세 페이지 진입 자체가 실패하거나 종목이 없는 경우
            print(f"    [-] 스킵: ID {cid} - 종목 정보(AGE_PK)를 찾을 수 없음")
            
        time.sleep(1.0)

if __name__ == "__main__":
    run_autopilot()