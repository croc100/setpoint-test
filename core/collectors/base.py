import os
import sys
import importlib
import json
import datetime as dt

# [환경 설정] PYTHONPATH에 루트 디렉토리 추가
BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if BASE_DIR not in sys.path:
    sys.path.append(BASE_DIR)

RAW_TOURNAMENT_DIR = os.path.join(BASE_DIR, "data", "raw", "tournaments")

# [크롤링 타겟 정의] 파일명(module)이 정확해야 합니다.
TARGET_COLLECTORS = [
    {"name": "BAEF (배프)", "module": "core.collectors.baef"},
    {"name": "WEEKUK (위꾹)", "module": "core.collectors.wekkuk"},
    {"name": "SPONET (스포넷)", "module": "core.collectors.sponet"},
    {"name": "FACECOK (페이스콕)", "module": "core.collectors.facecock"},
    {"name": "UDONGBAE (우동배)", "module": "core.collectors.nearminton"},
]

def run_all_collectors():
    """등록된 모든 크롤러를 가동하여 하나의 통합 JSON 파일을 생성합니다."""
    print("="*60)
    print("[*] 5개 플랫폼 통합 크롤링 파이프라인 가동 (Single JSON Aggregation)")
    print("="*60)

    os.makedirs(RAW_TOURNAMENT_DIR, exist_ok=True)
    all_tournaments = []

    for i, target in enumerate(TARGET_COLLECTORS, 1):
        name = target["name"]
        module_path = target["module"]
        
        print(f"\n[{i}/5] {name} 데이터 수집 준비...")
        
        try:
            # 1. 모듈 동적 로드
            collector_module = importlib.import_module(module_path)
            
            # 2. 실행 함수 검증 및 호출
            if hasattr(collector_module, 'collect_tournaments'):
                print(f"  [+] {name} 수집 모듈 가동 중...")
                
                # [핵심] 개별 모듈은 저장 대신 데이터를 Return 해야 합니다.
                result_list = collector_module.collect_tournaments()
                
                if result_list and isinstance(result_list, list):
                    all_tournaments.extend(result_list)
                    print(f"  [v] {name}: {len(result_list)}개 대회 수집 완료")
                else:
                    print(f"  [-] {name}: 수집된 대회가 없거나 반환 형식이 잘못되었습니다.")
            else:
                print(f"  [!] 구조 에러: {module_path} 내부에 'collect_tournaments' 함수가 없습니다.")
                
        except ModuleNotFoundError:
            print(f"  [!] 경로 에러: '{module_path}' 모듈을 찾을 수 없습니다. 파일명을 확인하십시오.")
        except Exception as e:
            print(f"  [!] {name} 수집 중 치명적 에러 발생: {e}")

    # 3. 통합 데이터 JSON 저장
    if all_tournaments:
        timestamp = dt.datetime.now().strftime('%Y%m%d_%H%M%S')
        
        # 보관용 히스토리 파일
        history_file = os.path.join(RAW_TOURNAMENT_DIR, f"tournaments_{timestamp}.json")
        with open(history_file, 'w', encoding='utf-8') as f:
            json.dump(all_tournaments, f, ensure_ascii=False, indent=2)
            
        # DB 로더가 바라볼 최신 고정 파일 (Overwrite)
        latest_file = os.path.join(RAW_TOURNAMENT_DIR, "tournaments_latest.json")
        with open(latest_file, 'w', encoding='utf-8') as f:
            json.dump(all_tournaments, f, ensure_ascii=False, indent=2)

        print("\n" + "="*60)
        print(f"✅ 통합 수집 완료: 총 {len(all_tournaments)}개 대회 확보")
        print(f"  - 저장 경로: {latest_file}")
        print("="*60)
    else:
        print("\n[!] 수집된 데이터가 없습니다.")

if __name__ == "__main__":
    run_all_collectors()