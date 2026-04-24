"""
update_tournament_status
========================
end_date 기준으로 대회 상태를 자동 갱신합니다.

  draft / ongoing  →  end_date < 오늘  →  finished
  draft            →  start_date <= 오늘 <= end_date  →  ongoing

cron_collect.sh 에서 매일 1회 실행합니다.
"""
import datetime
from django.core.management.base import BaseCommand
from core.models import Tournament


class Command(BaseCommand):
    help = '날짜 기준으로 대회 status 자동 갱신 (draft/ongoing → finished)'

    def handle(self, *args, **options):
        today = datetime.date.today()

        # 종료된 대회 → finished
        finished = Tournament.objects.filter(
            end_date__lt=today,
            status__in=['draft', 'ongoing'],
        ).update(status='finished')

        # 진행 중인 대회 → ongoing
        ongoing = Tournament.objects.filter(
            start_date__lte=today,
            end_date__gte=today,
            status='draft',
        ).update(status='ongoing')

        self.stdout.write(self.style.SUCCESS(
            f'상태 갱신 완료 — finished: {finished}개 / ongoing: {ongoing}개'
        ))
