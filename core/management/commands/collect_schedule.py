"""
collect_schedule — 자동화용 정기 수집 커맨드

사용 예 (crontab):
  # 매일 새벽 3시: 신규 대회 수집 + 전적 20개씩 처리
  0 3 * * * /path/to/.venv/bin/python /path/to/manage.py collect_schedule >> /var/log/setpoint_collect.log 2>&1

  # 6시간마다 전적 수집 (과거 데이터 점진적 소화)
  0 */6 * * * /path/to/.venv/bin/python /path/to/manage.py collect_schedule --stats-only >> /var/log/setpoint_collect.log 2>&1

[흐름]
  1단계: collect_tournaments  → 신규 대회 목록 DB 적재
  2단계: collect_stats        → 종료 대회 전적 수집 (--limit 개씩, --sleep 딜레이)
         과거 대회도 매 실행마다 조금씩 소화 → 시간을 두고 전체 수집 완료
"""
import datetime as dt

from django.core.management.base import BaseCommand
from django.core.management import call_command


# 수집 순서 — 가벼운 것 먼저
SOURCES = ['NEARMINTON', 'FACECOK', 'WEEKUK', 'SPONET', 'BAEF']

# collect_stats 지원 플랫폼 (FACECOK·NEARMINTON은 수집기 미완성)
STATS_SOURCES = {'WEEKUK', 'SPONET', 'BAEF'}

# 한 번 실행당 플랫폼별 최대 처리 대회 수 (서버 부하 조절)
DEFAULT_STATS_LIMIT = 20
# 대회 내 API 요청 간 딜레이 (초)
DEFAULT_SLEEP = 0.5


class Command(BaseCommand):
    help = '정기 자동화용: 대회 수집 → 전적 수집을 플랫폼별 순서대로 실행.'

    def add_arguments(self, parser):
        parser.add_argument(
            '--source', type=str, default=None,
            help='특정 플랫폼만 처리 (기본: 전체)',
        )
        parser.add_argument(
            '--no-tournaments', action='store_true',
            help='대회 목록 수집을 건너뜀 (전적만)',
        )
        parser.add_argument(
            '--stats-only', action='store_true',
            help='전적 수집만 실행 (대회 목록 수집 생략). --no-tournaments 와 동일.',
        )
        parser.add_argument(
            '--no-stats', action='store_true',
            help='전적 수집을 건너뜀 (대회 목록만)',
        )
        parser.add_argument(
            '--limit', type=int, default=DEFAULT_STATS_LIMIT,
            help=f'플랫폼당 전적 처리 최대 대회 수 (기본: {DEFAULT_STATS_LIMIT})',
        )
        parser.add_argument(
            '--sleep', type=float, default=DEFAULT_SLEEP,
            help=f'전적 수집 API 요청 간 딜레이(초) (기본: {DEFAULT_SLEEP})',
        )

    def handle(self, *args, **options):
        started_at = dt.datetime.now()
        self.stdout.write(f'[{started_at:%Y-%m-%d %H:%M}] collect_schedule 시작')

        sources      = [options['source'].upper()] if options['source'] else SOURCES
        skip_tourney = options['no_tournaments'] or options['stats_only']
        skip_stats   = options['no_stats']
        limit        = options['limit']
        sleep        = options['sleep']
        errors       = []

        # ── 1단계: 대회 목록 수집 ──────────────────────────
        if not skip_tourney:
            for source in sources:
                self.stdout.write(f'\n{"="*50}')
                self.stdout.write(f'[{source}] 대회 목록 수집...')
                try:
                    call_command(
                        'collect_tournaments',
                        source=source,
                        incremental=True,
                        verbosity=1,
                    )
                except Exception as e:
                    msg = f'[{source}] 대회 수집 실패: {e}'
                    self.stdout.write(self.style.ERROR(msg))
                    errors.append(msg)

        # ── 2단계: 전적 수집 (collect_stats) ──────────────
        if not skip_stats:
            stats_sources = [s for s in sources if s in STATS_SOURCES]
            if stats_sources:
                self.stdout.write(f'\n{"="*50}')
                self.stdout.write(
                    f'[전적 수집] 대상: {stats_sources} | '
                    f'플랫폼당 최대 {limit}개 | sleep={sleep}s'
                )
                try:
                    call_command(
                        'collect_stats',
                        source=options['source'].upper() if options['source'] else None,
                        limit=limit,
                        sleep=sleep,
                        dry_run=False,
                        skip_load=False,
                        verbosity=1,
                    )
                except Exception as e:
                    msg = f'[collect_stats] 실패: {e}'
                    self.stdout.write(self.style.ERROR(msg))
                    errors.append(msg)

        elapsed = (dt.datetime.now() - started_at).seconds
        self.stdout.write(f'\n[완료] 소요시간: {elapsed//60}분 {elapsed%60}초')

        if errors:
            self.stdout.write(self.style.WARNING(f'[경고] 오류 {len(errors)}건:'))
            for e in errors:
                self.stdout.write(f'  - {e}')
        else:
            self.stdout.write(self.style.SUCCESS('[정상 완료]'))
