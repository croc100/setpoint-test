import requests
import json

# 1. 환경 설정 (100님이 캡처하신 정보 기반)
BADDY_TOKEN = "eyJyZWdEYXRlIjoxNzc2Mjc2MzU0MjIzLCJ0eXAiOiJKV1QiLCJhbGciOiJIUzI1NiJ9.eyJtYmVyTm8iOjQ5OTAyLCJleHAiOjE3NzYzNjI3NTR9.8E-AyaLevSUOzcEZq0iS64J1HDVpDv4F5sIGa4v05Go"

HEADERS = {
    "accept-encoding": "gzip",
    "content-type": "application/json",
    "cookie": f"BADDY_TOKEN={BADDY_TOKEN}",
    "host": "real.badmintonfriends.co.kr",
    "user-agent": "Dart/3.6 (dart:io)"
}

def fetch_match_result(contest_id, age_pk):
    # 100님이 낚아채신 바로 그 주소
    url = f"https://real.badmintonfriends.co.kr/comp/intime/apply/match/result/{contest_id}/team"
    params = {"agePk": age_pk}
    
    print(f"[*] 요청 전송: {url} (agePk: {age_pk})")
    
    try:
        response = requests.get(url, headers=HEADERS, params=params, timeout=10)
        
        if response.status_code == 200:
            result_json = response.json()
            # 터미널에서 보기 좋게 정렬하여 출력
            print("\n[v] 서버 응답 데이터 (JSON):")
            print(json.dumps(result_json, indent=4, ensure_ascii=False))
            
            # 성적 유추를 위한 핵심 키가 있는지 확인하는 로직 (예시)
            data = result_json.get("result", [])
            if data:
                print("\n" + "="*50)
                print(f"[*] 총 {len(data)}팀의 성적이 확인되었습니다.")
                print("="*50)
        else:
            print(f"[!] 요청 실패: 상태 코드 {response.status_code}")
            print(response.text)
            
    except Exception as e:
        print(f"[!] 에러 발생: {e}")

if __name__ == "__main__":
    # 테스트하고 싶은 대회 ID와 종목 PK 입력
    fetch_match_result("278", "4476")