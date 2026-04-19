import os
import sys
import importlib
import json
import datetime as dt

BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if BASE_DIR not in sys.path:
    sys.path.append(BASE_DIR)

RAW_TOURNAMENT_DIR = os.path.join(BASE_DIR, "data", "raw", "tournaments")

TARGET_COLLECTORS = [
    {"name": "BAEF (배프)",     "source": "BAEF",       "module": "core.collectors.baef"},
    {"name": "WEEKUK (위꾹)",    "source": "WEEKUK",     "module": "core.collectors.wekkuk"},
    {"name": "SPONET (스포넷)",  "source": "SPONET",     "module": "core.collectors.sponet"},
    {"name": "FACECOK (페이스콕)","source": "FACECOK",   "module": "core.collectors.facecock"},
    {"name": "UDONGBAE (우동배)", "source": "NEARMINTON", "module": "core.collectors.nearminton"},
]


def run_all_collectors(known_ids: dict = None, only_source: str = None):
    """
    등록된 모든 크롤러를 가동하여 통합 대회 리스트를 반환합니다.

    known_ids: {source: set(external_id)} — 이미 DB에 있는 ID는 각 collector가 건너뜀
    only_source: 특정 플랫폼만 실행 (예: "BAEF")
    """
    print("=" * 60)
    print("[*] 5개 플랫폼 통합 크롤링 파이프라인 가동")
    print("=" * 60)

    os.makedirs(RAW_TOURNAMENT_DIR, exist_ok=True)
    known_ids = known_ids or {}
    all_tournaments = []

    targets = [t for t in TARGET_COLLECTORS if not only_source or t["source"] == only_source]

    for i, target in enumerate(targets, 1):
        name = target["name"]
        source = target["source"]
        module_path = target["module"]

        print(f"\n[{i}/{len(targets)}] {name} 데이터 수집 준비...")

        try:
            collector_module = importlib.import_module(module_path)

            if not hasattr(collector_module, 'collect_tournaments'):
                print(f"  [!] 구조 에러: {module_path} 내부에 'collect_tournaments' 함수가 없습니다.")
                continue

            print(f"  [+] {name} 수집 모듈 가동 중...")
            result_list = collector_module.collect_tournaments(
                known_ids=known_ids.get(source, set())
            )

            if result_list and isinstance(result_list, list):
                all_tournaments.extend(result_list)
                print(f"  [v] {name}: {len(result_list)}개 대회 수집 완료")
            else:
                print(f"  [-] {name}: 수집된 대회가 없거나 반환 형식이 잘못되었습니다.")

        except ModuleNotFoundError:
            print(f"  [!] 경로 에러: '{module_path}' 모듈을 찾을 수 없습니다.")
        except Exception as e:
            print(f"  [!] {name} 수집 중 에러 발생: {e}")

    if all_tournaments:
        timestamp = dt.datetime.now().strftime('%Y%m%d_%H%M%S')
        history_file = os.path.join(RAW_TOURNAMENT_DIR, f"tournaments_{timestamp}.json")
        latest_file = os.path.join(RAW_TOURNAMENT_DIR, "tournaments_latest.json")

        for path in (history_file, latest_file):
            with open(path, 'w', encoding='utf-8') as f:
                json.dump(all_tournaments, f, ensure_ascii=False, indent=2)

        print("\n" + "=" * 60)
        print(f"[완료] 총 {len(all_tournaments)}개 대회 확보")
        print(f"  저장 경로: {latest_file}")
        print("=" * 60)
    else:
        print("\n[!] 수집된 데이터가 없습니다.")

    return all_tournaments


if __name__ == "__main__":
    run_all_collectors()
