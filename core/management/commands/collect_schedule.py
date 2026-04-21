"""
collect_schedule — 자동화용 정기 수집 커맨드

사용 예 (crontab):
  # 매일 새벽 3시: 전체 플랫폼 대회 + 선수 수집
  0 3 * * * /path/to/.venv/bin/python /path/to/manage.py collect_schedule >> /var/log/setpoint_collect.log 2>&1

  # 1시간마다 NEARMINTON만 (신규 대회 빠른 감지)
  0 * * * * /path/to/.venv/bin/python /path/to/manage.py collect_schedule --source NEARMINTON
"""
import datetime as dt
import traceback

from django.core.management.base import BaseCommand
from django.core.management import call_command


# 수집 순서 — 가벼운 것 먼저
SOURCES = ['NEARMINTON', 'FACECOK', 'WEEKUK', 'SPONET', 'BAEF']


class Command(BaseCommand):
    help = '정기 자동화용: 대회 수집 → 선수 전적 수집을 플랫폼별 순서대로 실행.'

    def add_arguments(self, parser):
        parser.add_argument(
            '--source', type=str, default=None,
            help='특정 플랫폼만 처리 (기본: 전체)',
        )
        parser.add_argument(
            '--no-players', action='store_true',
            help='대회만 수집하고 선수 전적 수집은 건너뜀',
        )
        parser.add_argument(
            '--limit', type=int, default=0,
            help='플랫폼당 처리할 최대 대회 수 (기본: 전체)',
        )

    def handle(self, *args, **options):
        started_at = dt.datetime.now()
        self.stdout.write(f'[{started_at:%Y-%m-%d %H:%M}] collect_schedule 시작')

        sources = [options['source']] if options['source'] else SOURCES
        errors = []

        for source in sources:
            self.stdout.write(f'\n{"="*50}')
            self.stdout.write(f'[{source}] 대회 수집...')
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
                continue

            if options['no_players']:
                continue

            self.stdout.write(f'[{source}] 선수 전적 수집...')
            try:
                kwargs = {'source': source}
                if options['limit'] > 0:
                    kwargs['limit'] = options['limit']
                call_command('collect_player_stats', **kwargs)
            except Exception as e:
                msg = f'[{source}] 선수 수집 실패: {e}'
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
