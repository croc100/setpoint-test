import os
import sys
import json
import glob

# ---------------------------------------------------------
# [1] 장고 환경(Environment) 완벽 분리 및 초기화
# ---------------------------------------------------------
# 이 스크립트가 어디서 실행되든 무조건 프로젝트 최상단을 가리키도록 절대 경로 강제 주입
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE_DIR not in sys.path:
    sys.path.append(BASE_DIR)

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

# [주의] django.setup()은 반드시 앱 모델들을 import 하기 '전'에 실행되어야 함
import django
django.setup()

# 이제 안전하게 모델 임포트
from django.db import transaction
from core.models import Tournament, Player, PlayerDailyStats, Source

# ---------------------------------------------------------
# [2] 데이터 적재 로직 (멱등성 보장)
# ---------------------------------------------------------

def load_tournaments():
    """대회 정보 적재: 모든 JSON 파일을 읽어 최신 정보로 Update/Insert"""
    file_pattern = os.path.join(BASE_DIR, "data", "raw", "tournaments", "*.json")
    files = sorted(glob.glob(file_pattern))
    
    if not files:
        print("[!] 적재할 대회 JSON 파일이 없습니다.")
        return

    print(f"[*] 총 {len(files)}개의 대회 JSON 파일을 처리합니다.")
    
    for file_path in files:
        with open(file_path, "r", encoding="utf-8") as f:
            data = json.load(f)

        # 트랜잭션 묶기: 파일 하나 단위로 안전하게 처리
        with transaction.atomic():
            for item in data:
                Tournament.objects.update_or_create(
                    external_id=item['external_id'],
                    defaults={
                        "name": item['name'],
                        "start_date": item.get('start_date'),  # None 방어
                        "region_raw": item.get('region_raw', ''),
                        "external_url": item.get('external_url', ''),
                        "source": item.get('source', Source.BAEF)
                    }
                )
        print(f"[+] 완료: {os.path.basename(file_path)}")


def load_player_stats():
    """선수 전적 정보 적재: 참조 무결성 방어 및 트랜잭션 적용"""
    file_pattern = os.path.join(BASE_DIR, "data", "raw", "players", "*.json")
    files = sorted(glob.glob(file_pattern))
    
    if not files:
        print("[!] 적재할 선수 전적 JSON 파일이 없습니다.")
        return

    print(f"[*] 총 {len(files)}개의 선수 전적 JSON 파일을 처리합니다.")

    for file_path in files:
        with open(file_path, "r", encoding="utf-8") as f:
            data = json.load(f)

        with transaction.atomic():
            for item in data:
                # 1. 외래키(대회) 존재 여부 검증 (방어 로직)
                tournament_obj = Tournament.objects.filter(external_id=item['tournament_external_id']).first()
                if not tournament_obj:
                    print(f"  [경고] 매칭되는 대회(ID:{item['tournament_external_id']})가 DB에 없어 해당 전적을 건너뜁니다.")
                    continue # 대회가 없으면 이 선수의 이번 전적은 넣지 않음

                # 2. 선수 마스터 데이터 확보
                player, _ = Player.objects.get_or_create(
                    external_uid=item['external_uid'],
                    defaults={
                        "name": item['player_name'],
                        "club": item.get('club', ''),
                        "source": Source.BAEF
                    }
                )

                # 3. 일별 전적 적재
                PlayerDailyStats.objects.update_or_create(
                    player=player,
                    date=item['date'],
                    tournament=tournament_obj, # tournament도 식별 기준에 포함 (하루에 2개 대회 참가 가능성)
                    defaults={
                        "gender": item['stats'].get('gender', ''),
                        "category_age_band": item['stats'].get('age_band', ''),
                        "category_level": item['stats'].get('level', ''),
                        "rank": item['stats'].get('rank'),
                        "win_count": item['stats'].get('win_count', 0),
                        "loss_count": item['stats'].get('loss_count', 0)
                    }
                )
        print(f"[+] 완료: {os.path.basename(file_path)}")

# ---------------------------------------------------------
# [3] 메인 실행 오케스트레이터
# ---------------------------------------------------------
if __name__ == "__main__":
    print("="*50)
    print("🚀 데이터베이스 적재(Loader) 파이프라인 가동")
    print("="*50)
    
    print("\n[Phase 1] 대회 정보(Tournament) 로딩...")
    load_tournaments()
    
    print("\n[Phase 2] 선수 전적(Player Stats) 로딩...")
    load_player_stats()
    
    print("\n" + "="*50)
    print("✅ 모든 데이터베이스 적재가 안전하게 완료되었습니다.")
    print("="*50)