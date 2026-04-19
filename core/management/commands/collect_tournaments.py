import datetime as dt
from django.core.management.base import BaseCommand
from core.models import Tournament


class Command(BaseCommand):
    help = '5개 플랫폼에서 대회 목록을 수집하여 DB에 저장합니다.'

    def add_arguments(self, parser):
        parser.add_argument(
            '--incremental', action='store_true',
            help='이미 DB에 있는 external_id는 수집 시 건너뜁니다 (속도 향상)'
        )
        parser.add_argument(
            '--source', type=str, default=None,
            help='특정 플랫폼만 수집 (예: BAEF, WEEKUK, SPONET, FACECOK, NEARMINTON)'
        )

    def handle(self, *args, **options):
        incremental = options['incremental']
        only_source = options['source']

        # 증분 수집: source별로 이미 있는 external_id를 미리 로드
        known_ids: dict[str, set] = {}
        if incremental:
            self.stdout.write('[*] 기존 수집 캐시 로딩 중...')
            for row in Tournament.objects.values('source', 'external_id'):
                s = row['source']
                eid = row['external_id']
                if eid:
                    known_ids.setdefault(s, set()).add(eid)
            total_known = sum(len(v) for v in known_ids.values())
            self.stdout.write(f'    → {total_known}개 대회 캐시됨')

        from core.collectors.base import run_all_collectors
        self.stdout.write('[*] 대회 수집 시작...')
        all_tournaments = run_all_collectors(
            known_ids=known_ids,
            only_source=only_source,
        )

        if not all_tournaments:
            self.stdout.write(self.style.WARNING('[!] 수집된 대회가 없습니다.'))
            return

        created_count = 0
        updated_count = 0

        for t in all_tournaments:
            source = t.get('source', '')
            external_id = t.get('external_id')
            start_date = _parse_date(t.get('start_date'))
            end_date = _parse_date(t.get('end_date')) or start_date

            defaults = {
                'name': t.get('name', ''),
                'start_date': start_date,
                'end_date': end_date,
                'venue': t.get('venue', ''),
                'region_raw': t.get('region_raw', ''),
                'external_url': t.get('external_url', ''),
            }

            if external_id:
                obj, created = Tournament.objects.update_or_create(
                    source=source,
                    external_id=external_id,
                    defaults=defaults,
                )
            else:
                # external_id가 없으면 URL 기준으로 deduplicate
                obj, created = Tournament.objects.update_or_create(
                    external_url=t.get('external_url', ''),
                    defaults={'source': source, **defaults},
                )

            if created:
                created_count += 1
                self.stdout.write(f'  [신규] {obj.name} ({source})')
            else:
                updated_count += 1

        self.stdout.write(self.style.SUCCESS(
            f'\n[완료] 신규 {created_count}건 / 업데이트 {updated_count}건'
        ))


def _parse_date(value) -> dt.date | None:
    if not value:
        return None
    if isinstance(value, dt.date):
        return value
    try:
        parts = str(value).split('-')
        return dt.date(int(parts[0]), int(parts[1]), int(parts[2]))
    except Exception:
        return None
