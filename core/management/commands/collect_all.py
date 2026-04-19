from django.core.management.base import BaseCommand
from django.core.management import call_command


class Command(BaseCommand):
    help = '대회 수집 → 선수 전적 수집을 순서대로 실행합니다.'

    def add_arguments(self, parser):
        parser.add_argument(
            '--source', type=str, default=None,
            help='특정 플랫폼만 처리 (예: BAEF, WEEKUK)',
        )
        parser.add_argument(
            '--no-players', action='store_true',
            help='대회만 수집하고 선수 전적은 건너뜀',
        )

    def handle(self, *args, **options):
        source = options['source']

        self.stdout.write('=' * 50)
        self.stdout.write('[1/2] 대회 수집 시작')
        self.stdout.write('=' * 50)

        tournament_kwargs = {'incremental': True}
        if source:
            tournament_kwargs['source'] = source
        call_command('collect_tournaments', **tournament_kwargs)

        if options['no_players']:
            return

        self.stdout.write('\n' + '=' * 50)
        self.stdout.write('[2/2] 선수 전적 수집 시작')
        self.stdout.write('=' * 50)

        player_kwargs = {}
        if source:
            player_kwargs['source'] = source
        call_command('collect_player_stats', **player_kwargs)
