"""
backfill_player_level.py
========================
PlayerDailyStats.category_level 필드를 기반으로
Player.level 을 소급 적용합니다.

실행:
    python manage.py backfill_player_level            # 전체
    python manage.py backfill_player_level --source SPONET
    python manage.py backfill_player_level --dry-run

알고리즘:
  1. 각 선수의 PlayerDailyStats 중 가장 최신 날짜의 category_level 을 가져온다.
  2. BAEF 는 old pipeline 으로 적재된 레코드의 category_level/age_band 가 비어있어
     JSONL 파일을 직접 읽어 category_full → 급수 추출로 보강한다.
  3. Player.level 이 비어있거나 --overwrite 플래그가 있으면 업데이트한다.
"""

import glob
import json
import re
from pathlib import Path

from django.core.management.base import BaseCommand
from django.db.models import Q, Subquery, OuterRef, Value
from django.db.models.functions import Coalesce

# 유효 급수 목록 (이 안에 없으면 저장 안 함)
VALID_LEVELS = {
    'S조', '자강', '준자강',
    'A조', 'B조', 'C조', 'D조', 'E조', 'F조',
    '1부', '2부', '3부', '4부',
}


def _normalize_level(raw: str) -> str:
    """category_level / category_age_band / category_full 에서 급수만 추출."""
    if not raw:
        return ''
    raw = raw.strip()
    if raw in VALID_LEVELS:
        return raw
    m = re.search(r'(S조|자강|준자강|A조|B조|C조|D조|E조|F조|1부|2부|3부|4부)', raw)
    return m.group(1) if m else ''


def _read_jsonl(path) -> list:
    result = []
    p = Path(path)
    if not p.exists():
        return result
    with open(p, 'r', encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    result.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
    return result


class Command(BaseCommand):
    help = "PlayerDailyStats / BAEF JSONL 기반으로 Player.level 을 소급 적용합니다."

    def add_arguments(self, parser):
        parser.add_argument('--source', type=str, default=None,
                            help="특정 플랫폼만 처리 (BAEF / WEEKUK / SPONET …)")
        parser.add_argument('--overwrite', action='store_true',
                            help="이미 level 이 있는 선수도 덮어씀")
        parser.add_argument('--dry-run', action='store_true',
                            help="실제 저장 없이 결과만 출력")

    def handle(self, *args, **options):
        from django.conf import settings
        from core.models import Player, PlayerDailyStats

        source   = (options.get('source') or '').upper() or None
        overwrite = options['overwrite']
        dry_run   = options['dry_run']
        raw_dir   = Path(settings.BASE_DIR) / "data" / "raw"

        total_updated = 0

        # ──────────────────────────────────────────────
        # STEP 1 : PlayerDailyStats.category_level 기반 (SPONET/WEEKUK/FACECOK/NEARMINTON)
        # ──────────────────────────────────────────────
        qs = Player.objects.all()
        if source:
            qs = qs.filter(source=source)
        if not overwrite:
            qs = qs.filter(level='')

        self.stdout.write(f"[STEP 1] PlayerDailyStats 기반 업데이트 — 대상: {qs.count()}명"
                          + (" (dry-run)" if dry_run else ""))

        recent_level_sq = (
            PlayerDailyStats.objects
            .filter(player=OuterRef('pk'))
            .exclude(Q(category_level='') | Q(category_level=None))
            .order_by('-date')
            .values('category_level')[:1]
        )
        recent_band_sq = (
            PlayerDailyStats.objects
            .filter(player=OuterRef('pk'))
            .exclude(Q(category_age_band='') | Q(category_age_band=None))
            .order_by('-date')
            .values('category_age_band')[:1]
        )

        qs_ann = qs.annotate(
            _level_from_stats=Coalesce(
                Subquery(recent_level_sq),
                Subquery(recent_band_sq),
                Value(''),
            )
        )

        bulk = []
        step1_updated = step1_skipped = 0
        for player in qs_ann.iterator(chunk_size=500):
            raw   = player._level_from_stats or ''
            level = _normalize_level(raw)
            if not level:
                step1_skipped += 1
                continue

            if dry_run:
                self.stdout.write(f"  [dry] {player.name} ({player.source}) → {level}")
            else:
                player.level = level
                bulk.append(player)
            step1_updated += 1

            if not dry_run and len(bulk) >= 500:
                Player.objects.bulk_update(bulk, ['level'])
                bulk.clear()

        if not dry_run and bulk:
            Player.objects.bulk_update(bulk, ['level'])

        self.stdout.write(self.style.SUCCESS(
            f"  업데이트: {step1_updated}명 / 스킵: {step1_skipped}명"
        ))
        total_updated += step1_updated

        # ──────────────────────────────────────────────
        # STEP 2 : BAEF JSONL 파일 직접 읽기
        #   old pipeline 적재 레코드는 category_level/age_band 가 비어있어
        #   JSONL 의 category_full 에서 급수를 추출해 직접 업데이트
        # ──────────────────────────────────────────────
        if source and source != 'BAEF':
            self.stdout.write(self.style.SUCCESS(f"\n[전체 완료] 총 {total_updated}명 업데이트"))
            return

        baef_files = sorted(glob.glob(str(raw_dir / "players" / "baef_players_*.jsonl")))
        if not baef_files:
            self.stdout.write("\n[STEP 2] BAEF JSONL 파일 없음 — 스킵")
            self.stdout.write(self.style.SUCCESS(f"\n[전체 완료] 총 {total_updated}명 업데이트"))
            return

        self.stdout.write(f"\n[STEP 2] BAEF JSONL 기반 업데이트 — {len(baef_files)}개 파일"
                          + (" (dry-run)" if dry_run else ""))

        # {(name, club): level} 매핑 구축
        name_club_level: dict[tuple, str] = {}
        for p_file in baef_files:
            for row in _read_jsonl(p_file):
                cat = row.get('category_full', '')
                level = _normalize_level(cat)
                if not level:
                    continue
                for i in (1, 2):
                    name = (row.get(f'player{i}_name') or '').strip()
                    club = (row.get(f'player{i}_affiliation') or '').strip()
                    if name:
                        key = (name, club)
                        # 이미 더 높은 우선순위 급수가 있으면 덮어쓰지 않음
                        if key not in name_club_level:
                            name_club_level[key] = level

        self.stdout.write(f"  JSONL에서 추출된 (이름, 동호회) 조합: {len(name_club_level)}개")

        if dry_run:
            for (name, club), level in list(name_club_level.items())[:10]:
                self.stdout.write(f"  [dry] {name} ({club}) → {level}")
            self.stdout.write("  ...")
            self.stdout.write(self.style.SUCCESS(f"\n[전체 완료] 총 {total_updated}명 업데이트 (dry-run)"))
            return

        step2_updated = 0
        # 배치 업데이트: BAEF 선수 중 level='' 인 것만 (overwrite 없으면)
        baef_qs = Player.objects.filter(source='BAEF')
        if not overwrite:
            baef_qs = baef_qs.filter(level='')

        bulk = []
        for player in baef_qs.iterator(chunk_size=500):
            key   = (player.name, player.club)
            level = name_club_level.get(key)
            if not level:
                continue
            player.level = level
            bulk.append(player)
            step2_updated += 1

            if len(bulk) >= 500:
                Player.objects.bulk_update(bulk, ['level'])
                bulk.clear()

        if bulk:
            Player.objects.bulk_update(bulk, ['level'])

        self.stdout.write(self.style.SUCCESS(
            f"  BAEF JSONL 기반 업데이트: {step2_updated}명"
        ))
        total_updated += step2_updated
        self.stdout.write(self.style.SUCCESS(f"\n[전체 완료] 총 {total_updated}명 업데이트"))
