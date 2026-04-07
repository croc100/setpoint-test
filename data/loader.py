import os
import sys
import json
import glob
import django

# Django 환경 설정
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.append(BASE_DIR)
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
django.setup()

from core.models import Tournament, Player, PlayerDailyStats, Source

def load_tournaments():
    """대회 정보 적재"""
    files = sorted(glob.glob(os.path.join(BASE_DIR, "data/raw/tournaments/*.json")), reverse=True)
    if not files: return
    # ... 기존 Tournament.objects.update_or_create 로직 ...

def load_player_stats():
    """선수 전적 정보 적재"""
    files = sorted(glob.glob(os.path.join(BASE_DIR, "data/raw/players/*.json")), reverse=True)
    if not files:
        print("[!] 적재할 선수 전적 JSON이 없습니다.")
        return

    with open(files[0], "r", encoding="utf-8") as f:
        data = json.load(f)

    for item in data:
        # 1. 선수 마스터 데이터 확보 (없으면 생성)
        player, _ = Player.objects.get_or_create(
            external_uid=item['external_uid'],
            defaults={
                "name": item['player_name'],
                "club": item['club'],
                "source": Source.BAEF
            }
        )

        # 2. 일별 전적(통계) 적재
        # tournament_external_id를 통해 이미 적재된 대회 객체를 찾음
        tournament_obj = Tournament.objects.filter(external_id=item['tournament_external_id']).first()

        PlayerDailyStats.objects.update_or_create(
            player=player,
            date=item['date'],
            defaults={
                "tournament": tournament_obj,
                "gender": item['stats']['gender'],
                "category_age_band": item['stats']['age_band'],
                "category_level": item['stats']['level'],
                "rank": item['stats']['rank'],
                "win_count": item['stats']['win_count'],
                "loss_count": item['stats']['loss_count']
            }
        )
    print(f"[*] 선수 전적 적재 완료: {files[0]}")

if __name__ == "__main__":
    # 실행 시 인자를 주거나 순차적으로 실행
    print("--- 대회 정보 로딩 ---")
    load_tournaments()
    print("\n--- 선수 전적 로딩 ---")
    load_player_stats()