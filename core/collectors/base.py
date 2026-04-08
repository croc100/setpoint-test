import os
import sys
import time

# [환경 설정] PYTHONPATH에 루트 디렉토리 추가 (모듈 import용)
BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if BASE_DIR not in sys.path:
    sys.path.append(BASE_DIR)

# [수집기 모듈 임포트] 
# (추후 5개 사이트 수집기가 완성될 때마다 이곳에 추가하십시오)
try:
    from core.collectors.baef_collector import collect_tournaments as baef_tournaments
except ImportError as e:
    print(f"[!] BAEF 모듈 로드 실패: {e}")
    baef_tournaments = None

# 향후 추가될 수집기 예시
# from core.collectors.site_a_collector import collect_tournaments as site_a_tournaments
# ...

def run_all_collectors():
    """등록된 모든 크롤러를 순차적으로 가동하여 JSON 파일을 생성합니다."""
    print("="*50)
    print("[*] 전체 크롤링 파이프라인 가동 시작")
    print("="*50)

    # 1. BAEF (배프) 수집
    if baef_tournaments:
        print("\n[1] BAEF(배프) 데이터 수집 시작...")
        try:
            baef_tournaments()
            print("[+] BAEF 수집 정상 완료 (data/raw/tournaments/ 확인 요망)")
        except Exception as e:
            print(f"[!] BAEF 수집 중 치명적 에러 발생: {e}")
    
    # 2. SITE_A (스포넷 등 향후 추가)
    # print("\n[2] 스포넷 데이터 수집 시작...")
    # site_a_tournaments()
    
    # 3. SITE_B ...
    
    time.sleep(1) # 서버 보호를 위한 쿨타임
    print("\n" + "="*50)
    print("[*] 모든 크롤링 프로세스가 종료되었습니다.")
    print("[*] 생성된 JSON 파일을 VSC에서 검증한 후 DB에 적재하십시오.")
    print("="*50)

if __name__ == "__main__":
    run_all_collectors()