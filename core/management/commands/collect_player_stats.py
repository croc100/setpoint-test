import datetime as dt

from django.core.management.base import BaseCommand

from core.models import MatchRecord, Player, PlayerDailyStats, Tournament


class Command(BaseCommand):
    help = '종료된 대회의 선수 전적을 수집하여 DB에 저장합니다.'

    def add_arguments(self, parser):
        parser.add_argument(
            '--source', type=str, default=None,
            help='특정 플랫폼만 처리 (예: BAEF, WEEKUK)'
        )
        parser.add_argument(
            '--limit', type=int, default=0,
            help='처리할 최대 대회 수 (기본값: 0 = 전체)'
        )
        parser.add_argument(
            '--tournament-id', type=int, default=None,
            help='특정 대회 ID만 처리 (DB pk)'
        )
        parser.add_argument(
            '--retry-failed', action='store_true',
            help='stats_collected=True인 대회도 재수집'
        )

    def handle(self, *args, **options):
        today = dt.date.today()

        # 대상 대회 쿼리: 종료된 대회 중 아직 선수 전적을 수집하지 않은 것
        qs = Tournament.objects.filter(end_date__lt=today)

        if not options['retry_failed']:
            qs = qs.filter(stats_collected=False)

        if options['tournament_id']:
            qs = qs.filter(pk=options['tournament_id'])

        if options['source']:
            qs = qs.filter(source=options['source'])

        qs = qs.order_by('end_date')

        limit = options['limit']
        if limit > 0:
            qs = qs[:limit]

        tournaments = list(qs)
        if not tournaments:
            self.stdout.write(self.style.WARNING('[!] 수집 대상 대회가 없습니다.'))
            return

        self.stdout.write(f'[*] 선수 전적 수집 대상: {len(tournaments)}개 대회')

        from core.collectors.player.base_player import collect_player_stats_for_tournament

        total_players = 0
        for i, tournament in enumerate(tournaments, 1):
            self.stdout.write(
                f'\n[{i}/{len(tournaments)}] {tournament.name} '
                f'({tournament.source}, {tournament.end_date})'
            )

            if not tournament.start_date:
                self.stdout.write('  [-] start_date 없음 → 건너뜀')
                continue

            tournament_dict = {
                'external_id': tournament.external_id,
                'name': tournament.name,
                'start_date': tournament.start_date.isoformat() if tournament.start_date else None,
                'source': tournament.source,
                'external_url': tournament.external_url,
            }

            try:
                stats = collect_player_stats_for_tournament(tournament_dict)
            except Exception as e:
                self.stdout.write(self.style.ERROR(f'  [!] 수집 실패: {e}'))
                continue

            if not stats:
                self.stdout.write('  [-] 수집된 선수 없음 (미구현 플랫폼이거나 대회 결과 없음)')
                tournament.stats_collected = True
                tournament.save(update_fields=['stats_collected'])
                continue

            saved = _save_stats(tournament, stats)
            total_players += saved
            self.stdout.write(f'  [완료] {saved}명 저장됨')

            tournament.stats_collected = True
            tournament.save(update_fields=['stats_collected'])

        self.stdout.write(self.style.SUCCESS(
            f'\n[전체 완료] 총 {total_players}명의 전적 저장됨'
        ))


def _save_stats(tournament: Tournament, stats: list) -> int:
    """Player + PlayerDailyStats + MatchRecord를 DB에 저장. 반환: 저장된 선수 수"""
    saved = 0
    for stat in stats:
        name = (stat.get('player_name') or '').strip()
        club = (stat.get('player_club') or '').strip()
        if not name:
            continue

        player, _ = Player.objects.get_or_create(
            name=name,
            club=club,
            source=tournament.source,
        )

        win_count = int(stat.get('win_count') or 0)
        loss_count = int(stat.get('loss_count') or 0)
        total = win_count + loss_count
        win_rate = round(win_count / total, 4) if total > 0 else 0.0

        daily_stat, created = PlayerDailyStats.objects.get_or_create(
            player=player,
            tournament=tournament,
            category_age_band=stat.get('category_age_band') or '',
            category_level=stat.get('category_level') or '',
            defaults={
                'date': tournament.start_date,
                'gender': stat.get('gender') or '',
                'rank': stat.get('rank'),
                'final_status': stat.get('final_status'),
                'win_count': win_count,
                'loss_count': loss_count,
                'win_rate': win_rate,
                'gain_point': int(stat.get('gain_point') or 0),
                'is_heuristic': bool(stat.get('is_heuristic', False)),
            },
        )

        if created:
            for match in stat.get('matches') or []:
                MatchRecord.objects.create(
                    daily_stat=daily_stat,
                    bracket_name=match.get('bracket_name') or '',
                    is_win=bool(match.get('is_win', False)),
                    my_score=int(match.get('my_score') or 0),
                    op_score=int(match.get('op_score') or 0),
                    opponent_names=match.get('opponent_names') or '',
                    opponent_club=match.get('opponent_club') or '',
                )
            saved += 1

    return saved
