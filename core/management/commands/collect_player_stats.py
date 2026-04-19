import datetime as dt
from typing import Optional

from django.core.management.base import BaseCommand

from core.models import MatchRecord, Player, PlayerDailyStats, Tournament


class Command(BaseCommand):
    help = '종료된 대회의 선수 전적을 수집하여 DB에 저장합니다.'

    def add_arguments(self, parser):
        parser.add_argument(
            '--source', type=str, default=None,
            help='특정 플랫폼만 처리 (예: BAEF, WEEKUK)',
        )
        parser.add_argument(
            '--limit', type=int, default=0,
            help='처리할 최대 대회 수 (기본값: 0 = 전체, BAEF에는 적용되지 않음)',
        )
        parser.add_argument(
            '--tournament-id', type=int, default=None,
            help='특정 대회 DB pk만 처리',
        )
        parser.add_argument(
            '--retry-failed', action='store_true',
            help='stats_collected=True인 대회도 재수집',
        )

    def handle(self, *args, **options):
        only_source = options['source']

        # ── BAEF: 모바일 API 일괄 수집 (별도 분기) ──────────────────────────
        if only_source in (None, 'BAEF'):
            self._handle_baef(options)

        # ── Wekkuk / 나머지: per-tournament 수집 ────────────────────────────
        non_baef_sources = ['WEEKUK', 'SPONET', 'FACECOK', 'NEARMINTON']
        targets = [only_source] if only_source and only_source != 'BAEF' else non_baef_sources
        self._handle_per_tournament(options, targets)

    # ──────────────────────────────────────────────────────────────────────
    def _handle_baef(self, options):
        from core.collectors.player.baef_player import collect_all_player_stats, get_token

        token = get_token()
        if not token:
            self.stdout.write(self.style.WARNING(
                '[!] BAEF_TOKEN이 없어 BAEF 수집을 건너뜁니다.'
            ))
            return

        self.stdout.write('[*] BAEF 선수 전적 수집 시작 (모바일 API)...')
        results = collect_all_player_stats(token)

        if not results:
            self.stdout.write('  [-] 수집된 BAEF 대회가 없습니다.')
            return

        total_saved = 0
        for r in results:
            title = r['contest_title']
            stats = r['stats']

            # 대회명으로 DB Tournament 매칭
            tournament = _find_tournament_by_name('BAEF', title)
            if not tournament:
                self.stdout.write(f"  [-] DB 매칭 실패: '{title}' → 건너뜀")
                continue

            if tournament.stats_collected and not options['retry_failed']:
                self.stdout.write(f"  [-] 이미 수집됨: {title}")
                continue

            saved = _save_stats(tournament, stats)
            total_saved += saved
            tournament.stats_collected = True
            tournament.save(update_fields=['stats_collected'])
            self.stdout.write(f"  [완료] {title}: {saved}명 저장")

        self.stdout.write(self.style.SUCCESS(f'[BAEF 완료] 총 {total_saved}명 저장'))

    # ──────────────────────────────────────────────────────────────────────
    def _handle_per_tournament(self, options, sources: list):
        today = dt.date.today()

        qs = Tournament.objects.filter(
            source__in=sources,
            end_date__lt=today,
        )
        if not options['retry_failed']:
            qs = qs.filter(stats_collected=False)
        if options['tournament_id']:
            qs = qs.filter(pk=options['tournament_id'])

        qs = qs.order_by('end_date')
        if options['limit'] > 0:
            qs = qs[:options['limit']]

        tournaments = list(qs)
        if not tournaments:
            self.stdout.write('[*] per-tournament 수집 대상 없음')
            return

        self.stdout.write(f'[*] per-tournament 수집 대상: {len(tournaments)}개 대회')

        from core.collectors.player.base_player import collect_player_stats_for_tournament

        total_saved = 0
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
                'start_date': tournament.start_date.isoformat(),
                'source': tournament.source,
                'external_url': tournament.external_url,
            }

            try:
                stats = collect_player_stats_for_tournament(tournament_dict)
            except Exception as e:
                self.stdout.write(self.style.ERROR(f'  [!] 수집 실패: {e}'))
                continue

            if not stats:
                self.stdout.write('  [-] 수집된 선수 없음')
                tournament.stats_collected = True
                tournament.save(update_fields=['stats_collected'])
                continue

            saved = _save_stats(tournament, stats)
            total_saved += saved
            tournament.stats_collected = True
            tournament.save(update_fields=['stats_collected'])
            self.stdout.write(f'  [완료] {saved}명 저장')

        self.stdout.write(self.style.SUCCESS(f'\n[per-tournament 완료] 총 {total_saved}명 저장'))


# ──────────────────────────────────────────────────────────────────────────
# 헬퍼 함수
# ──────────────────────────────────────────────────────────────────────────

def _find_tournament_by_name(source: str, title: str) -> Optional['Tournament']:
    """BAEF 대회명으로 DB Tournament 검색. 정확한 매칭 우선, 없으면 포함 검색."""
    qs = Tournament.objects.filter(source=source)
    exact = qs.filter(name=title).first()
    if exact:
        return exact
    # 대회명 앞 10글자로 포함 검색 (web/mobile 명칭 차이 대응)
    keyword = title[:10].strip()
    return qs.filter(name__icontains=keyword).first() if keyword else None


def _save_stats(tournament: Tournament, stats: list) -> int:
    """Player + PlayerDailyStats + MatchRecord DB 저장. 반환: 신규 저장 선수 수"""
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

        win_count  = int(stat.get('win_count') or 0)
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


