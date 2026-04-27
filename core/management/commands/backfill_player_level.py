"""
backfill_player_level.py
========================
PlayerDailyStats.category_level 필드를 기반으로
Player.level 을 소급 적용합니다.

실행:
    python manage.py backfill_player_level          # 전체
    python manage.py backfill_player_level --source SPONET
    python manage.py backfill_player_level --dry-run

알고리즘:
  1. 각 선수의 PlayerDailyStats 중 가장 최신 날짜의 category_level 을 가져온다.
  2. BAEF 는 category_level 이 없으므로 category_age_band 를 fallback 으로 사용한다.
  3. Player.level 이 비어있거나 --overwrite 플래그가 있으면 업데이트한다.
"""

import re
from django.core.management.base import BaseCommand
from django.db.models import Subquery, OuterRef, Q

# 유효 급수 목록 (이 안에 없으면 저장 안 함)
VALID_LEVELS = {
    'S조', '자강', '준자강',
    'A조', 'B조', 'C조', 'D조', 'E조', 'F조',
    '1부', '2부', '3부', '4부',
}


def _normalize_level(raw: str) -> str:
    """category_level / category_age_band 원시값에서 급수만 추출."""
    if not raw:
        return ''
    raw = raw.strip()
    # 그대로 유효하면 반환
    if raw in VALID_LEVELS:
        return raw
    # 복합 문자열에서 추출 (예: "남자복식 A조", "오픈 B조")
    m = re.search(r'(S조|자강|준자강|A조|B조|C조|D조|E조|F조|1부|2부|3부|4부)', raw)
    return m.group(1) if m else ''


class Command(BaseCommand):
    help = "PlayerDailyStats 기반으로 Player.level 을 소급 적용합니다."

    def add_arguments(self, parser):
        parser.add_argument('--source', type=str, default=None,
                            help="특정 플랫폼만 처리 (BAEF / WEEKUK / SPONET …)")
        parser.add_argument('--overwrite', action='store_true',
                            help="이미 level 이 있는 선수도 덮어씀")
        parser.add_argument('--dry-run', action='store_true',
                            help="실제 저장 없이 결과만 출력")

    def handle(self, *args, **options):
        from core.models import Player, PlayerDailyStats

        source = (options.get('source') or '').upper() or None
        overwrite = options['overwrite']
        dry_run = options['dry_run']

        qs = Player.objects.all()
        if source:
            qs = qs.filter(source=source)
        if not overwrite:
            qs = qs.filter(level='')

        total = qs.count()
        self.stdout.write(f"[backfill_player_level] 대상 선수: {total}명"
                          + (" (dry-run)" if dry_run else ""))

        updated = skipped = 0

        # category_level 기반 Subquery (최신 날짜 우선)
        recent_level_sq = (
            PlayerDailyStats.objects
            .filter(player=OuterRef('pk'))
            .exclude(Q(category_level='') | Q(category_level=None))
            .order_by('-date')
            .values('category_level')[:1]
        )
        # BAEF fallback: category_age_band
        recent_band_sq = (
            PlayerDailyStats.objects
            .filter(player=OuterRef('pk'))
            .exclude(Q(category_age_band='') | Q(category_age_band=None))
            .order_by('-date')
            .values('category_age_band')[:1]
        )

        from django.db.models import Subquery, Value
        from django.db.models.functions import Coalesce

        qs = qs.annotate(
            _level_from_stats=Coalesce(
                Subquery(recent_level_sq),
                Subquery(recent_band_sq),
                Value(''),
            )
        )

        bulk = []
        for player in qs.iterator(chunk_size=500):
            raw = player._level_from_stats or ''
            level = _normalize_level(raw)
            if not level:
                skipped += 1
                continue

            if not dry_run:
                player.level = level
                bulk.append(player)
            else:
                self.stdout.write(
                    f"  [dry] {player.name} ({player.club}) → {level}"
                )
            updated += 1

            if not dry_run and len(bulk) >= 500:
                Player.objects.bulk_update(bulk, ['level'])
                bulk.clear()

        if not dry_run and bulk:
            Player.objects.bulk_update(bulk, ['level'])

        self.stdout.write(self.style.SUCCESS(
            f"[완료] 업데이트: {updated}명 / 급수 미확인 스킵: {skipped}명"
        ))
