# core/management/commands/collect_stats.py
"""
collect_stats.py
================
status='finished' 이고 is_stats_fetched=False 인 대회만 골라
플랫폼별 전적 수집기를 실행하고, 완료 후 load_stats로 DB에 적재합니다.

[현재 지원 플랫폼]
    BAEF    → core/collectors/status_baef.py
    WEEKUK  → core/collectors/status_wekkuk.py

[실행 방법]
    python manage.py collect_stats                   # 전체 플랫폼
    python manage.py collect_stats --source BAEF     # 특정 플랫폼만
    python manage.py collect_stats --limit 10        # 한 번에 최대 10개 대회
    python manage.py collect_stats --dry-run         # 대상 목록만 출력

[흐름]
    ① DB 쿼리 : status='finished' AND is_stats_fetched=False
    ② 플랫폼별 hunter 실행 → JSONL 파일 저장
    ③ load_stats 커맨드 호출 → JSONL → DB 적재
    ④ 성공한 대회만 is_stats_fetched=True 마킹
"""

from django.core.management.base import BaseCommand
from django.core.management import call_command
from django.utils import timezone


# 지원 플랫폼 목록
# 함수명 컨벤션: run_{source소문자}_stats_hunter
SUPPORTED_SOURCES = {
    "BAEF":   "core.collectors.status_baef",
    "WEEKUK": "core.collectors.status_wekkuk",
}


class Command(BaseCommand):
    help = "종료된 대회의 전적을 수집하고 DB에 적재합니다. (BAEF, WEEKUK 지원)"

    def add_arguments(self, parser):
        parser.add_argument(
            '--source',
            type=str,
            default=None,
            help="특정 플랫폼만 처리 (BAEF / WEEKUK). 생략 시 전체.",
        )
        parser.add_argument(
            '--limit',
            type=int,
            default=None,
            help="플랫폼별 최대 처리 대회 수. 생략 시 미수집 전체.",
        )
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help="실제 수집 없이 대상 목록만 출력합니다.",
        )
        parser.add_argument(
            '--skip-load',
            action='store_true',
            help="수집 후 DB 적재(load_stats)를 건너뜁니다. 디버깅용.",
        )

    def handle(self, *args, **options):
        from core.models import Tournament

        target_source = (options.get('source') or "").upper() or None
        limit         = options['limit']
        dry_run       = options['dry_run']
        skip_load     = options['skip_load']

        # 처리할 플랫폼 결정
        if target_source:
            if target_source not in SUPPORTED_SOURCES:
                self.stderr.write(f"[!] 지원하지 않는 source: {target_source}")
                self.stderr.write(f"    지원 목록: {list(SUPPORTED_SOURCES.keys())}")
                return
            sources = [target_source]
        else:
            sources = list(SUPPORTED_SOURCES.keys())

        self.stdout.write(f"\n{'='*55}")
        self.stdout.write(f"[*] 전적 수집 파이프라인 시작 | 대상: {sources}")
        self.stdout.write(f"{'='*55}\n")

        total_marked = 0

        for source in sources:
            self.stdout.write(f"\n── [{source}] 처리 시작 ──")

            # ──────────────────────────────────────────────
            # ① 수집 대상 쿼리
            #    - status='finished'      : 종료된 대회만
            #    - is_stats_fetched=False : 아직 전적 없는 것만
            #    end_date 오름차순 → 오래된 것부터 처리
            # ──────────────────────────────────────────────
            qs = Tournament.objects.filter(
                status='finished',
                is_stats_fetched=False,
                source=source,
            ).order_by('end_date')

            if limit:
                qs = qs[:limit]

            targets = list(qs)

            if not targets:
                self.stdout.write(f"  [-] 수집 대상 없음 (모두 완료됨)")
                continue

            self.stdout.write(f"  [*] 대상: {len(targets)}개 대회")
            for t in targets:
                self.stdout.write(
                    f"      - [{t.external_id}] {t.name} ({t.end_date or '날짜미상'})"
                )

            if dry_run:
                self.stdout.write("  [dry-run] 실제 수집 생략")
                continue

            # ──────────────────────────────────────────────
            # ② 플랫폼별 hunter 실행
            #    각 모듈의 run_{source소문자}_stats_hunter 호출
            #    반환값: 수집 성공한 external_id 리스트
            # ──────────────────────────────────────────────
            external_ids = [t.external_id for t in targets if t.external_id]
            id_to_obj    = {t.external_id: t for t in targets}

            try:
                import importlib
                module  = importlib.import_module(SUPPORTED_SOURCES[source])
                fn_name = f"run_{source.lower()}_stats_hunter"
                hunter  = getattr(module, fn_name)

                self.stdout.write(f"  [*] {fn_name} 실행 중...")
                success_ids = hunter(external_ids)

            except Exception as e:
                self.stderr.write(f"  [!] hunter 실행 에러: {e}")
                continue

            if not success_ids:
                self.stderr.write(f"  [!] 성공한 대회가 없습니다.")
                continue

            # ──────────────────────────────────────────────
            # ③ DB 적재 (load_stats 커맨드 호출)
            #    --skip-load 옵션으로 생략 가능 (디버깅용)
            # ──────────────────────────────────────────────
            if not skip_load:
                self.stdout.write(
                    f"  [*] DB 적재 시작 (load_stats --source {source})..."
                )
                try:
                    call_command('load_stats', source=source)
                except Exception as e:
                    self.stderr.write(f"  [!] load_stats 에러: {e}")
                    self.stderr.write(
                        "      마킹을 건너뜁니다. 다음 실행에서 재시도됩니다."
                    )
                    continue

            # ──────────────────────────────────────────────
            # ④ 성공한 대회만 완료 마킹
            #    실패 대회는 마킹 안 함 → 다음 실행에서 재시도
            # ──────────────────────────────────────────────
            now = timezone.now()
            marked_count = 0

            for eid in success_ids:
                t = id_to_obj.get(eid)
                if t:
                    t.is_stats_fetched = True
                    t.stats_fetched_at = now
                    t.save(update_fields=['is_stats_fetched', 'stats_fetched_at'])
                    marked_count += 1

            self.stdout.write(
                self.style.SUCCESS(f"  [v] {source}: {marked_count}개 마킹 완료")
            )
            total_marked += marked_count

        self.stdout.write(f"\n{'='*55}")
        self.stdout.write(
            self.style.SUCCESS(f"[완료] 총 {total_marked}개 대회 전적 수집 완료")
        )
        self.stdout.write(f"{'='*55}\n")
